"""Query helpers for the dmr API.

``FieldsQuery`` replaces the former ``FieldsParam``: the include/exclude
wire contract stays identical (same query parameter names, same
``__all__`` handling, same 400 on unknown field names, same narrowed
JSON output), but the implementation dropped the dynamic-schema
machinery (``create_schema`` + ``TypeAdapter`` per request) in favour of
one rule:

    validate the object against the full (all-optional) response schema,
    then dump it with ``model_dump(include=...)``.

That is a straight projection over a fixed schema — no schema classes
are built at request time.

Design note (PoC evaluation): the frontend never sends ``include`` or
``exclude`` (verified against wodore-frontend-quasar). The parameters
exist for external consumers; if they are ever retired it must happen
via a new API version (removing them makes responses observably larger).
"""

from collections.abc import Sequence
from enum import Enum
from http import HTTPStatus
from typing import Any, TypeVar

import pydantic
from dmr import APIError
from pydantic import Field

_M = TypeVar("_M", bound=type[pydantic.BaseModel])


class FieldsQuery(pydantic.BaseModel):
    """``include``/``exclude`` field narrowing, shared by many endpoints."""

    model_config = pydantic.ConfigDict(extra="ignore")

    include: str | None = Field(
        None,
        description=(
            "Comma separated list with field names, use `__all__` in order "
            "to include every field."
        ),
    )
    exclude: str | None = Field(
        None,
        description=(
            "Comma separated list with field names, if set it uses all "
            "fields except the excluded ones."
        ),
    )


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
                "code": "invalid_field_name",
                "detail": f"'{', '.join(missing)}' {were} {possible}",
            },
            status_code=HTTPStatus.BAD_REQUEST,
        )
    return names


def include_set(
    model: type[pydantic.BaseModel],
    fields: FieldsQuery,
    default_include: Sequence[str] | None = None,
) -> set[str]:
    """Resolve the effective include-set, mirroring ``FieldsParam``.

    Rules (same as the old ``get_include`` after ``update_default``):
    - neither include nor exclude given → ``default_include`` (or the
      required fields only when no default exists)
    - include given → those names plus required fields
    - only exclude given → all fields
    - i18n: including a translatable field also includes ``{name}_i18n``
    - the result always subtracts ``exclude``
    """
    available = list(model.model_fields)
    required = {name for name, info in model.model_fields.items() if info.is_required()}

    include_raw = fields.include
    exclude_raw = fields.exclude
    if include_raw is None and exclude_raw is None and default_include is not None:
        if isinstance(default_include, str):
            include_raw = default_include  # '__all__' passes through
        else:
            include_raw = ",".join(default_include)

    include = _parse(include_raw, available)
    exclude = _parse(exclude_raw, available)

    if not include and exclude:
        include = list(available)
    else:
        include += list(required)

    # i18n companion fields ride along with their translatable field
    db_model = getattr(getattr(model, "Meta", None), "model", None)
    i18n = getattr(db_model, "i18n", None) if db_model is not None else None
    if i18n is not None:
        i18n_fields = set(i18n.field.fields)
        include += [f"{name}_i18n" for name in include if name in i18n_fields]

    return set(include) - set(exclude)


def dump_fields(
    model: type[_M],
    obj: Any,
    fields: FieldsQuery,
    default_include: Sequence[str] | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate ``obj`` against ``model`` and dump the narrowed fields.

    ``model`` must be an all-optional schema variant (the old
    ``*Optional`` schemas) so that any narrowed subset validates.
    ``context`` reaches nested validators (e.g. the hut-type symbol
    resolver needs the request to build absolute URLs).
    """
    names = include_set(model, fields, default_include)
    instance = model.model_validate(obj, context=context)
    return instance.model_dump(include=names)


def dump_fields_list(
    model: type[_M],
    objs: Sequence[Any],
    fields: FieldsQuery,
    default_include: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """``dump_fields`` for a list of objects."""
    names = include_set(model, fields, default_include)
    return [model.model_validate(obj).model_dump(include=names) for obj in objs]
