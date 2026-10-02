"""Query helpers for the dmr API.


**Sparse fieldsets** (openspec ``switch-to-sparse-fieldsets``): JSON:API-style
response narrowing via ``?fields[TYPE]=name1,name2``.

- Positive selection only (no ``exclude`` — "everything except X" silently
  grows payloads when fields are added).
- Type-scoped: ``fields[huts]=slug,sources&fields[sources]=slug,name``
  narrows the hut DTO and each nested source DTO independently (one
  nesting level).
- Allowlist-validated: unknown TYPE → 400 ``invalid_field_type``, unknown
  field name → 400 ``invalid_field_name``; ``__all__`` selects everything.
- The legacy ``include``/``exclude`` parameters are REMOVED (no consumer
  existed): sending them answers 400 ``invalid_parameter`` naming the
  replacement. Pinned old API versions keep them via their frozen
  snapshots' contract.

Implementation: validate against the full (all-optional) response schema,
then dump with ``model_dump(include=...)`` — a projection over a fixed
schema, no dynamic schema classes at request time. ``include`` accepts
pydantic's nested form (``{"slug", "sources": {"slug", "name"}}``).
"""

from collections.abc import Sequence
from enum import Enum
from http import HTTPStatus
from typing import Any, ClassVar, TypeVar

import pydantic
from dmr import APIError
from pydantic import Field

from server.apps.api.error_codes import ErrorCode

_M = TypeVar("_M", bound=type[pydantic.BaseModel])


def _parse(raw: str | None, available: list[str]) -> list[str]:
    """Parse a comma list (or ``__all__``); 400 on unknown names."""
    if raw is None:
        return []
    if raw == "__all__":
        return list(available)
    names = [part.strip() for part in raw.split(",") if part.strip()]
    missing = [name for name in names if name not in available]
    if missing:
        possible = f"Possible names: {', '.join(available)}."
        were = (
            "is not a valid field name!"
            if len(missing) == 1
            else "are not valid field names!"
        )
        raise APIError(
            {
                "code": ErrorCode.invalid_field_name,
                "detail": f"'{', '.join(missing)}' {were} {possible}",
            },
            status_code=HTTPStatus.BAD_REQUEST,
        )
    return names


def _i18n_companions(model: type[pydantic.BaseModel], names: set[str]) -> set[str]:
    """Translatable fields ride along with their ``{name}_i18n`` sibling."""
    db_model = getattr(getattr(model, "Meta", None), "model", None)
    i18n = getattr(db_model, "i18n", None) if db_model is not None else None
    if i18n is None:
        return names
    i18n_fields = set(i18n.field.fields)
    return names | {f"{name}_i18n" for name in names if name in i18n_fields}


def _top_names(
    model: type[pydantic.BaseModel],
    spec: str,
    default_include: Sequence[str] | str | None = None,
) -> set[str]:
    """Effective top-level field set for one TYPE selection.

    Required fields are always kept; i18n companions ride along; without a
    selection the endpoint default (or required-only) applies.
    """
    required = {name for name, info in model.model_fields.items() if info.is_required()}

    if spec is None:
        if default_include is None:
            names: set[str] = set()
        elif isinstance(default_include, str):
            names = set(_parse(default_include, list(model.model_fields)))
        else:
            names = set(_parse(",".join(default_include), list(model.model_fields)))
    else:
        names = set(_parse(spec, list(model.model_fields)))

    names |= required
    return _i18n_companions(model, names)


class SparseFieldsQuery(pydantic.BaseModel):
    """Base for query models with a ``fields[TYPE]`` sparse-fieldset parameter.

    Endpoints compose with ``sparse_fields_query(type_name=DtoClass, ...)``
    which fixes the valid TYPE names (and their DTOs) per endpoint.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    FIELD_TYPES: ClassVar[dict[str, Any]] = {}

    fields: dict[str, str] | None = Field(
        None,
        description=(
            "Sparse fieldsets (JSON:API): ``fields[TYPE]=name1,name2`` "
            "narrows the response to the selected fields (one nesting "
            "level per type). ``__all__`` selects every field."
        ),
    )

    @pydantic.model_validator(mode="before")
    @classmethod
    def _collect_bracket_fields(cls, data: Any) -> Any:
        """Collect ``fields[TYPE]`` query keys; reject the legacy names."""
        if not isinstance(data, dict):
            return data

        for legacy in ("include", "exclude"):
            if legacy in data:
                raise APIError(
                    {
                        "code": ErrorCode.invalid_parameter,
                        "detail": (
                            f"The '{legacy}' parameter was removed. Use "
                            "'fields[TYPE]=name1,name2' (sparse fieldsets) "
                            "instead."
                        ),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        collected: dict[str, str] = {}
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if key.startswith("fields[") and key.endswith("]"):
                type_name = key[len("fields[") : -1]
                if type_name not in cls.FIELD_TYPES:
                    valid = ", ".join(sorted(cls.FIELD_TYPES))
                    raise APIError(
                        {
                            "code": ErrorCode.invalid_field_type,
                            "detail": (
                                f"'{type_name}' is not a valid field type. "
                                f"Valid types: {valid}."
                            ),
                        },
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                if isinstance(value, (list, tuple)):
                    value = ",".join(str(v) for v in value)
                collected[type_name] = str(value)
            else:
                cleaned[key] = value
        cleaned["fields"] = collected or None
        return cleaned


def sparse_fields_query(**field_types: type[pydantic.BaseModel]) -> type:
    """Build a query-model base declaring the valid ``fields[TYPE]`` names.

    ``sparse_fields_query(huts=HutSchemaDetails, sources=OrgSchema)`` —
    the first declared type is conventionally the endpoint's top-level
    response DTO; the description lists all valid types for the docs.
    """
    type_names = ", ".join(field_types)
    namespace = {
        "FIELD_TYPES": dict(field_types),
        "__annotations__": {"fields": dict[str, str] | None},
        "fields": Field(
            None,
            description=(
                "Sparse fieldsets (JSON:API): `fields[TYPE]=name1,name2` "
                "narrows the response to the selected fields (`__all__` = "
                f"every field). Valid TYPEs: {type_names}."
            ),
        ),
        "__doc__": f"Sparse fieldsets; valid types: {type_names}.",
    }
    return type("SparseFieldsQuery", (SparseFieldsQuery,), namespace)


def sparse_include(
    parsed: SparseFieldsQuery,
    top_type: str,
    default_include: Sequence[str] | str | None = None,
) -> set[str] | dict[str, Any]:
    """Resolve the pydantic ``model_dump(include=...)`` argument.

    Without a selection: the endpoint default as a flat set (required
    fields and i18n companions always kept). With selections: a nested
    include dict — the top type's names at the top level, every other
    type mapped onto its DTO field on the top model.
    """
    top_dto = parsed.FIELD_TYPES[top_type]
    fields_map = parsed.fields or {}

    if not fields_map:
        return _top_names(top_dto, None, default_include)

    # pydantic include dict: scalar fields map to Ellipsis, nested model
    # fields map to their own include set.
    top_names: set[str] = set()
    nested: dict[str, set[str]] = {}
    for type_name, spec in fields_map.items():
        if type_name == top_type:
            top_names |= set(_parse(spec, list(top_dto.model_fields)))
            continue
        # Nested type: must exist as a field on the top DTO.
        nested[type_name] = set(_parse(spec, list(top_dto.model_fields)))
    required = {n for n, i in top_dto.model_fields.items() if i.is_required()}
    top_names |= required
    top_names = _i18n_companions(top_dto, top_names)
    include: dict[str, Any] = {name: ... for name in top_names}
    include.update(nested)
    return include


def dump_sparse(
    model: type[_M],
    obj: Any,
    parsed: SparseFieldsQuery,
    top_type: str,
    default_include: Sequence[str] | str | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate ``obj`` against ``model`` and dump the narrowed fields.

    ``model`` must be an all-optional schema variant so any narrowed
    subset validates. ``context`` reaches nested validators (e.g. the
    hut-type symbol resolver needs the request for absolute URLs).
    """
    names = sparse_include(parsed, top_type, default_include)
    instance = model.model_validate(obj, context=context)
    return instance.model_dump(include=names)


def dump_sparse_list(
    model: type[_M],
    objs: Sequence[Any],
    parsed: SparseFieldsQuery,
    top_type: str,
    default_include: Sequence[str] | str | None = None,
) -> list[dict[str, Any]]:
    """``dump_sparse`` for a list of objects."""
    names = sparse_include(parsed, top_type, default_include)
    return [model.model_validate(obj).model_dump(include=names) for obj in objs]


class TristateEnum(str, Enum):
    """Tristate enum with `true`, `false` and `unset`."""

    true = "true"
    false = "false"
    unset = "unset"

    @property
    def bool(self) -> bool | None:
        """Returns either `None`, `True` or `False`."""
        if self.value == "unset":
            return None
        return self.value == "true"
