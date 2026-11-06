"""Transform pipeline: produce older API versions at the edge.

Handlers only implement the newest version. Response downgrades run
newest→oldest over every change newer than the requested version, keyed
by operation id (== URL name of the dmr route). GeoJSON helpers
transform ``features[*].properties``.

Application point: :mod:`server.apps.apiversions.middleware` transforms
every JSON response in place — uniformly for DTO endpoints and the
former direct-write GeoJSON endpoints (they are ordinary JSON
endpoints now).
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


def version_cache_key(request: HttpRequest) -> str:
    """ETag/cache key part for versioned responses (design.md D11).

    Joins the ETag key material so a conditional request for one version
    can never produce a 304 reusing another version's representation, and
    registering a transform changes the ETag even when the data did not.
    """
    version = getattr(request, "api_version", None) or "unversioned"
    return f"api:{version}:{registry.content_hash()}"
