"""Dict-level sparse fieldset projection for search endpoints.

Works on plain dicts (not pydantic models) — the search endpoints build
their results manually. The projection narrows top-level fields and
nested object/list fields based on ``fields[TYPE]`` selections.
"""

from __future__ import annotations

from typing import Any

from .query import SparseFieldsQuery, _parse


def project_fields(
    data: dict[str, Any],
    parsed: SparseFieldsQuery,
    top_type: str,
    field_map: dict[str, str],
    *,
    default_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Narrow a plain-dict response based on ``fields[TYPE]`` selections.

    Args:
        data: the full response dict (all fields, objects not slugs).
        parsed: the parsed query model (has .fields dict).
        top_type: the TYPE name for the top-level fields (e.g. "huts").
        field_map: maps TYPE name → field name on the data dict
            (e.g. {"hut_types": "hut_type", "sources": "sources"}).
            The top_type maps to the top level (implicit).
        default_fields: fields to include when no selection is given
            (backward-compatible default). None = all fields.
    """
    fields_map = parsed.fields or {}
    if not fields_map:
        if default_fields is None:
            return data
        return {k: v for k, v in data.items() if k in default_fields}

    result = dict(data)

    # Top-level selection
    top_spec = fields_map.get(top_type)
    if top_spec is not None:
        names = set(_parse(top_spec, list(result.keys())))
        result = {k: v for k, v in result.items() if k in names}

    # Nested type selections
    for type_name, spec in fields_map.items():
        if type_name == top_type:
            continue
        field_name = field_map.get(type_name)
        if field_name is None or field_name not in result:
            continue
        value = result[field_name]
        if value is None:
            continue

        if isinstance(value, list):
            result[field_name] = [_narrow_item(item, spec, type_name) for item in value]
        elif isinstance(value, dict):
            result[field_name] = _narrow_item(value, spec, type_name)

    return result


def _narrow_item(item: Any, spec: str, type_name: str) -> Any:
    """Narrow one nested object based on the spec."""
    if not isinstance(item, dict):
        return item
    # For wrapper dicts like {"open": {...}, "closed": {...}}, narrow
    # each inner object rather than the wrapper keys.
    if all(isinstance(v, dict) for v in item.values()) and spec != "__all__":
        return {
            key: _narrow_object(obj, spec, type_name)
            for key, obj in item.items()
            if isinstance(obj, dict)
        }
    return _narrow_object(item, spec, type_name)


def _narrow_object(obj: dict, spec: str, type_name: str) -> dict:
    """Narrow a flat object to the selected fields."""
    if spec == "__all__":
        return obj
    available = list(obj.keys())
    names = set(_parse(spec, available))
    return {k: v for k, v in obj.items() if k in names}
