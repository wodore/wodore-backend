"""Transform pipeline: produce older API versions at the edge.

Handlers only implement the newest version. Response downgrades run
newest→oldest over every change newer than the requested version, keyed by
Ninja operation id. GeoJSON helpers transform ``features[*].properties``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from . import registry
from .registry import Transform


def each(transform: Transform) -> Transform:
    """Apply ``transform`` to every item of a list response."""

    def _each(data: Any) -> Any:
        if isinstance(data, list):
            return [transform(item) for item in data]
        return data

    return _each


def feature_properties(transform: Transform) -> Transform:
    """Apply ``transform`` to ``features[*].properties`` of a FeatureCollection."""

    def _properties(data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            for feature in data["features"]:
                if isinstance(feature, dict) and "properties" in feature:
                    feature["properties"] = transform(feature["properties"])
        return data

    return _properties


def effective_operation_id(operation: Any, api: Any = None) -> str:
    """The operation id as it appears in the OpenAPI schema.

    Mirrors ninja's schema generation (``ninja/openapi/schema.py``):
    explicit ``operation_id`` or the generated ``module_FunctionName`` id.
    ``api`` is optional because ``operation.api`` is only populated when
    the URLs are generated — callers that run pre-binding (``wrap_api``)
    pass the ``NinjaAPI`` instance (or we fall back to computing the same
    id inline).
    """
    if getattr(operation, "operation_id", None):
        return operation.operation_id
    api = api or getattr(operation, "api", None)
    if api is not None:
        return api.get_openapi_operation_id(operation)
    name = operation.view_func.__name__
    module = operation.view_func.__module__
    return (module + "_" + name).replace(".", "_")


def downgrade_response(requested_version: str, operation_id: str, data: Any) -> Any:
    """Apply response downgrades (newest→oldest) for one operation."""
    for change in registry.changes_after(requested_version):
        transform = change.responses.get(operation_id)
        if transform is not None:
            data = transform(data)
    return data


def upgrade_request(requested_version: str, operation_id: str, data: Any) -> Any:
    """Apply request upgrades (oldest→newest) for one operation."""
    for change in reversed(registry.changes_after(requested_version)):
        transform = change.requests.get(operation_id)
        if transform is not None:
            data = transform(data)
    return data


def apply_response_transforms(
    request: HttpRequest, operation_id: str, data: Any
) -> Any:
    """Explicit transform helper for direct-write endpoints.

    ``huts.geojson`` and ``availability/{date}.geojson`` serialize with
    ``response.write(msgspec.json.encode(...))`` and bypass the Ninja
    renderer — they call this helper on the Python dict before encoding
    (design.md D5.3). No version pinned (or excluded operation) → no-op.
    """
    version = getattr(request, "api_version", None)
    if version is None or version == registry.current_version():
        return data
    return downgrade_response(version, operation_id, data)


def version_cache_key(request: HttpRequest) -> str:
    """ETag/cache key part for versioned responses (design.md D11).

    Joins the ETag key material so a conditional request for one version
    can never produce a 304 reusing another version's representation, and
    registering a transform changes the ETag even when the data did not.
    """
    version = getattr(request, "api_version", None) or "unversioned"
    return f"api:{version}:{registry.content_hash()}"
