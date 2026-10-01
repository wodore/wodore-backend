"""Swagger UI with a version switcher (api-docs spec: docs version switching).

Ninja's ``Swagger.render_page`` hardcodes the schema URL to the live
``openapi.json``; this subclass points it at ``openapi.json?api_version=``
for non-current versions and renders a small switcher bar listing all
supported versions (ninja's Swagger template has no native ``urls``
dropdown).
"""

from __future__ import annotations

import json
from typing import Any

from ninja.openapi.docs import Swagger, render_template

from django.http import HttpRequest, HttpResponse

from server.apps.apiversions import registry


class VersionedSwagger(Swagger):
    template = "apiversions/swagger_versioned.html"

    def render_page(
        self, request: HttpRequest, api: Any, **kwargs: Any
    ) -> HttpResponse:
        current = registry.current_version()
        version = getattr(request, "api_version", None) or current
        url = self.get_openapi_url(api, kwargs)
        if version != current:
            url = f"{url}?api_version={version}"
        self.settings["url"] = url

        from ninja.openapi.docs import _csrf_needed  # matching ninja's flow

        context = {
            "swagger_settings": json.dumps(self.settings, indent=1),
            "api": api,
            "add_csrf": _csrf_needed(api),
            "api_versions": sorted(registry.versions(), reverse=True),
            "current_api_version": current,
            "selected_api_version": version,
        }
        return render_template(request, self.template, self.template_cdn, context)
