"""Derive django-readers specs from pydantic response schemas.

Read-path companion to :mod:`server.apps.api.projection`: the schema that
defines the wire contract also drives the query. Plain fields become field
entries, nested schemas over model relations become relationship subtrees,
and a sparse ``fields[TYPE]`` selection restricts the spec to the requested
subset (unselected relations are neither selected nor prefetched).

Computed/aggregated fields (distance, availability, JSONB collections) are
NOT derived — supply them as explicit reader pairs via ``overrides`` (see
openspec/changes/adopt-django-readers-query-optimization/design.md for the
rationale and the mixing-safety analysis).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Union, get_args, get_origin

from django_readers import qs, specs
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Field, Model, Prefetch

# A django-readers reader pair: (prepare, project).
Pair = tuple[Any, Any]
# A django-readers spec tree.
Spec = list[Any]


def _to_one_pair(name: str, related_model: type[Model], child_spec: Spec) -> Pair:
    """Reader pair for a forward to-one relation, prefetched not joined.

    Two modeltrans traps make django-readers' default to-one handling
    (``select_related`` + ``only(name)``) unusable here:

    1. ``only('relation_name')`` implies ``select_related`` traversal of
       the relation; the multilingual queryset then defers sibling
       translated fields (e.g. ``Category.symbol_detailed``) and Django
       rejects the combination ("cannot be both deferred and traversed").
    2. any ``only()`` without ``i18n`` defers it, breaking translated
       attribute access (handled separately via ``_include_i18n``).

    Prefetching the relation and including only the ``<name>_id`` column
    sidesteps both at the cost of a second query. The child queryset also
    clears the related manager's own ``select_related`` defaults (e.g.
    Category pre-selects its symbol relations), which would collide with
    the child spec's field limiting the same way.
    """
    child_prepare, project_child = specs.process(child_spec)

    def prepare(queryset):
        child_qs = qs.pipe(qs.include_fields("pk"), child_prepare)(
            related_model._default_manager.all().select_related(None)
        )
        return qs.pipe(
            qs.include_fields(f"{name}_id"),
            qs.prefetch_related(Prefetch(name, queryset=child_qs)),
        )(queryset)

    def project(instance):
        related = getattr(instance, name)
        return project_child(related) if related is not None else None

    return prepare, project


def _unwrap_model(annotation: Any) -> type[BaseModel] | None:
    """Return the BaseModel subclass behind an annotation.

    Unwraps ``Optional[...]``/``Union[...]`` and container origins such as
    ``list[...]``/``Sequence[...]``; returns ``None`` for anything else.
    """
    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            if model := _unwrap_model(arg):
                return model
        return None
    if origin is not None:
        for arg in get_args(annotation):
            if model := _unwrap_model(arg):
                return model
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _candidate_names(name: str, info: FieldInfo) -> list[str]:
    """Python name first, then wire aliases (they may differ).

    ``AliasChoices`` (one field accepting several wire names, e.g.
    ``owner`` / ``hut_owner``) is unpacked — model-attr aliases are how
    the hut wire schemas map onto ORM field names.
    """
    names = [name]
    aliases: list[str] = []
    for alias in (info.alias, info.validation_alias):
        if isinstance(alias, str):
            aliases.append(alias)
        else:
            choices = getattr(alias, "choices", None)
            if choices:
                aliases.extend(c for c in choices if isinstance(c, str))
    for alias in aliases:
        if alias != name and alias not in names:
            names.append(alias)
    return names


def _find_field(model: type[Model], names: list[str]) -> Field | None:
    for candidate in names:
        try:
            return model._meta.get_field(candidate)
        except FieldDoesNotExist:
            continue
    return None


def spec_from_schema(
    model: type[Model],
    schema: type[BaseModel],
    *,
    fields: Collection[str] | None = None,
    overrides: Mapping[str, Pair] | None = None,
) -> Spec:
    """Derive a django-readers spec from a pydantic response schema.

    - plain schema field -> model field: field entry (``only()`` covers it)
    - nested schema over a model relation (FK/O2O prefetched via a custom
      pair — modeltrans-safe; M2M/reverse via the default relationship
      entry with the nested schema's fields as its subtree)
    - nested schema over a plain (e.g. JSON) model field: pass-through entry
    - relation with a scalar annotation (e.g. ``hut_type: int``): not
      derived — supply an override (the id needs a dedicated producer pair)
    - anything with no model field: must come via ``overrides``

    ``fields`` restricts the spec to the given names (python name or wire
    alias); ``overrides`` maps field names to reader pairs used verbatim.
    Raises ``ValueError`` listing fields that cannot be derived.
    """
    overrides = overrides or {}
    spec: Spec = []
    problems: list[str] = []

    for name, info in schema.model_fields.items():
        wire = str(info.validation_alias or info.alias or name)
        if fields is not None and name not in fields and wire not in fields:
            continue
        if name in overrides or wire in overrides:
            spec.append(overrides.get(name) or overrides[wire])
            continue

        candidates = _candidate_names(name, info)
        nested = _unwrap_model(info.annotation)
        model_field = _find_field(model, candidates)

        if nested is None:
            if model_field is None:
                problems.append(f"{name} (no model field)")
            elif model_field.is_relation:
                # Relation exposed as a scalar (usually an id): the plain
                # field entry would project the related instance instead.
                problems.append(
                    f"{name} (relation needs a nested schema or an override)"
                )
            else:
                spec.append(name)
            continue

        if model_field is None:
            problems.append(f"{name} (no model field)")
        elif model_field.is_relation:
            if model_field.many_to_one or model_field.one_to_one:
                # Forward to-one: custom prefetch pair (modeltrans-safe,
                # see _to_one_pair).
                spec.append(
                    {
                        model_field.name: _to_one_pair(
                            model_field.name,
                            model_field.related_model,
                            spec_from_schema(model_field.related_model, nested),
                        )
                    }
                )
            else:
                spec.append(
                    {
                        model_field.name: spec_from_schema(
                            model_field.related_model, nested
                        )
                    }
                )
        else:
            # Plain field typed as a nested schema (JSON passthrough).
            spec.append(name)

    if problems:
        msg = ", ".join(sorted(problems))
        raise ValueError(
            f"cannot derive spec for {schema.__name__} against {model.__name__}: "
            f"{msg}; supply reader pairs via overrides="
        )
    _include_i18n(model, schema, spec)
    return spec


def _include_i18n(model: type[Model], schema: type[BaseModel], spec: Spec) -> None:
    """Ensure the modeltrans ``i18n`` column is fetched.

    django-modeltrans backs translated attributes (``name``, ``description``
    ...) with the ``i18n`` JSON column. Any ``only()`` that omits it makes
    the queryset defer ``i18n``, and reading a translated attribute then
    raises. When the model carries the field and any field limiting will
    happen (i.e. we derived plain entries), keep ``i18n`` in the select.
    """
    try:
        model._meta.get_field("i18n")
    except FieldDoesNotExist:
        return
    if "i18n" not in spec:
        spec.append("i18n")
