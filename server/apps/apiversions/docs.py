"""Version-aware Swagger UI documentation (dmr).

Served at ``/v1/docs``.

Version switching uses Swagger UI's **native** ``urls`` dropdown in the
standalone topbar: every API version has a stable schema URL
(``/v1/openapi.json?api_version=<v>`` — snapshots for old versions, live
schema for the current one), so the dropdown switches client-side by
fetching that URL. ``?api_version=`` deep links still work: the server
pre-selects the matching entry via ``urls.primaryName``.

The topbar is a Swagger UI component styled by its own stylesheet —
it follows the page theme (light by default, dark under browser-level
darkening) with no custom CSS of ours involved. A pinned-old version
without a committed snapshot fails fast with an explicit 500 instead of
letting Swagger fetch a silently-wrong schema.
"""

from __future__ import annotations

import structlog
from dmr.openapi.views.swagger import SwaggerView
from dmr.settings import Settings, resolve_setting
from typing_extensions import override

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from server.apps.apiversions import registry
from server.apps.apiversions.management.commands.api_snapshot import load_snapshot

logger = structlog.get_logger("apiversions")

OPENAPI_JSON_PATH = "/v1/openapi.json"


def _missing_snapshot(version: str) -> HttpResponse:
    """Explicit 500: never silently serve the newest contract to an
    old-pinned client (CI's snapshot check should prevent this)."""
    logger.error("api_snapshot_missing", version=version)
    return HttpResponse(
        '{"code": "api_snapshot_missing", "detail": '
        f'"No committed OpenAPI snapshot for API version {version!r}."}}',
        content_type="application/json",
        status=500,
    )


class VersionedSwagger(SwaggerView):
    """Swagger UI with the API version dropdown pre-selected."""

    template_name = "apiversions/swagger_versioned.html"

    @override
    def get(self, request: HttpRequest) -> HttpResponse:
        """Render the Swagger UI page with the version dropdown."""
        current = registry.current_version()
        version = getattr(request, "api_version", None) or current

        if version != current and load_snapshot(version) is None:
            return _missing_snapshot(version)

        urls = [
            {"url": f"{OPENAPI_JSON_PATH}?api_version={v}", "name": v}
            for v in sorted(registry.versions(), reverse=True)
        ]
        return render(
            request,
            self.template_name,
            context={
                "title": self.schema.info.title,
                "swagger_config": {"urls": urls, "primary": version},
                "swagger_cdn": resolve_setting(Settings.openapi_static_cdn).get(
                    "swagger"
                ),
            },
            content_type=self.content_type,
        )
