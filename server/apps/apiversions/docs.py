"""Version-aware Swagger UI documentation (dmr).

Served at ``/v1/docs``. The current version renders the live dmr schema
inline; older versions render the committed snapshot for the pinned
version (loaded from ``openapi/<version>.json``).

Why the custom switcher bar instead of Swagger UI's native ``urls``
dropdown: version selection here is **server-side** (the page embeds
the snapshot for the pinned version — including transforms metadata
review), not a client-side schema-URL swap. dmr's template has no
native dropdown either, so the bar links to ``?api_version=<v>``
page reloads. Switching to the native dropdown is possible (every
version has a stable URL via ``/v1/openapi.json?api_version=``) but
would need a custom swagger-init script — kept for later if the bar
feels unworthy.
"""

from __future__ import annotations

import structlog
from dmr.openapi.views.base import OpenAPIView
from dmr.openapi.views.swagger import SwaggerView
from dmr.settings import Settings, resolve_setting
from typing_extensions import override

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from server.apps.apiversions import registry
from server.apps.apiversions.management.commands.api_snapshot import load_snapshot

logger = structlog.get_logger("apiversions")


def _schema_data(view: OpenAPIView, request: HttpRequest) -> HttpResponse | dict:
    """Live schema (current version) or committed snapshot (pinned old).

    Returns a ``dict`` for rendering, or an ``HttpResponse`` (500) when a
    pinned version has no snapshot — serving the live schema would
    silently hand an old-pinned client the NEWEST contract, so fail
    loudly (CI's snapshot check should prevent this from ever firing).
    """
    current = registry.current_version()
    version = getattr(request, "api_version", None) or current

    if version == current:
        return view.schema.convert(skip_validation=view.skip_validation)

    snapshot = load_snapshot(version)
    if snapshot is None:
        logger.error("api_snapshot_missing", version=version)
        return HttpResponse(
            '{"code": "api_snapshot_missing", "detail": '
            f'"No committed OpenAPI snapshot for API version {version!r}."}}',
            content_type="application/json",
            status=500,
        )
    snapshot.setdefault("info", {})["version"] = version
    return snapshot


class VersionedSwagger(SwaggerView):
    """Swagger UI that switches between API contract versions."""

    template_name = "apiversions/swagger_versioned.html"

    @override
    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the OpenAPI schema using the Swagger template."""
        schema_data = _schema_data(self, request)
        if isinstance(schema_data, HttpResponse):
            return schema_data

        current = registry.current_version()
        version = getattr(request, "api_version", None) or current
        return render(
            request,
            self.template_name,
            context={
                "title": self.schema.info.title,
                "schema": schema_data,
                "swagger_cdn": resolve_setting(Settings.openapi_static_cdn).get(
                    "swagger"
                ),
                "api_versions": sorted(registry.versions(), reverse=True),
                "selected_api_version": version,
            },
            content_type=self.content_type,
        )
