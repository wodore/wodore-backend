"""Swagger UI with a version switcher (api-docs spec: docs version switching).

The current version renders the live dmr schema inline; older versions
render the committed snapshot for the pinned version (loaded from
``openapi/<version>.json``). A small switcher bar lists all supported
versions — dmr's Swagger template has no native version dropdown either,
so this stays a custom template.
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


class VersionedSwagger(SwaggerView):
    """Swagger UI that switches between API contract versions."""

    template_name = "apiversions/swagger_versioned.html"

    @override
    def get(self, request: HttpRequest) -> HttpResponse:
        current = registry.current_version()
        version = getattr(request, "api_version", None) or current

        if version == current:
            schema_data = self.schema.convert(
                skip_validation=self.skip_validation,
            )
        else:
            snapshot = load_snapshot(version)
            if snapshot is None:
                # Serving the live schema here would silently hand an
                # old-pinned client the NEWEST contract — fail loudly
                # instead (CI's snapshot check should prevent this).
                logger.error("api_snapshot_missing", version=version)
                return HttpResponse(
                    '{"code": "api_snapshot_missing", "detail": '
                    f'"No committed OpenAPI snapshot for API version {version!r}."}}',
                    content_type="application/json",
                    status=500,
                )
            schema_data = snapshot
            schema_data.setdefault("info", {})["version"] = version

        cdn_config = resolve_setting(Settings.openapi_static_cdn)
        return render(
            request,
            self.template_name,
            context={
                "title": self.schema.info.title,
                "schema": schema_data,
                "swagger_cdn": cdn_config.get("swagger"),
                "api_versions": sorted(registry.versions(), reverse=True),
                "selected_api_version": version,
            },
            content_type=self.content_type,
        )
