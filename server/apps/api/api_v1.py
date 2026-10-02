"""/v1 API wiring on django-modern-rest (dmr).

Endpoints are dmr Controllers — plain Django class-based views wired
with ``dmr.routing.path``. Every JSON route carries ``name=<operation
id>``; the API-versioning middleware uses the URL name as endpoint
identity (no framework internals touched, see
``server.apps/apiversions/middleware.py``).
"""

from functools import lru_cache
from typing import Any

from dmr.openapi import build_schema
from dmr.openapi.config import OpenAPIConfig
from dmr.routing import Router

from django.http import HttpRequest, HttpResponse

from server.apps.apiversions import registry

API_DESCRIPTION = (
    "Clients pin a contract version with the `Api-Version` header or the "
    "`api_version` query parameter (e.g. `2026-10-01`); no version given "
    "serves the latest. Deprecated versions are announced via "
    "`Deprecation`/`Sunset` headers; see `/v1/version` for supported "
    "versions and `/CHANGELOG_API.md` (repo) for the API changelog."
)

# Import order mirrors the URL assembly below (most specific first).
from server.apps.categories import api as categories_api
from server.apps.feedbacks import api as feedbacks_api
from server.apps.geometries import api as geo_api
from server.apps.geometries import api_images as geo_images_api
from server.apps.huts.api import paths as huts_paths
from server.apps.meteo import api as meteo_api
from server.apps.organizations import api as organizations_api
from server.apps.symbols import api as symbols_api
from server.apps.utils import api as utils_api


def build_router() -> Router:
    """Assemble the /v1 router.

    Most specific prefixes first (geo/images before geo), the former
    ninja ``add_router`` order — preserved for URL resolution parity.
    """
    router = Router("v1/")
    # Tags mirror the former per-router tags (OpenAPI grouping).
    router.include(Router("geo/images/", geo_images_api.paths, tags=["geoimages"]))
    router.include(Router("geo/", geo_api.paths, tags=["geometries"]))
    router.include(Router("categories/", categories_api.paths, tags=["category"]))
    router.include(Router("huts/", huts_paths, tags=["hut"]))
    router.include(Router("meteo/", meteo_api.paths, tags=["meteo"]))
    router.include(
        Router("organizations/", organizations_api.paths, tags=["organization"])
    )
    router.include(Router("symbols/", symbols_api.paths, tags=["symbols"]))
    router.include(Router("feedback/", feedbacks_api.paths, tags=["feedback"]))
    # Root (version, sitemaps) last — least specific.
    router.include(Router("", utils_api.paths, tags=["utils"]))
    return router


router = build_router()

urlpatterns: list[Any] = [
    # The resolver already carries the 'v1/' prefix and the namespace.
    router.to_urlpatterns(namespace="v1"),
]


@lru_cache(maxsize=1)
def _cached_schema() -> Any:
    return build_schema(
        build_router(),
        config=OpenAPIConfig(
            title="Wodore API",
            version=registry.current_version(),  # refreshed per request below
            description=API_DESCRIPTION,
        ),
    )


def get_openapi_schema(request: HttpRequest | None = None) -> dict:
    """The live OpenAPI document (dict form).

    ``info.version`` always reflects the *current* registry state —
    tests may register temporary versions after import time.

    Operation titles use the endpoint slug: dmr derives ``summary``
    from the handler docstring's first paragraph, which for most
    endpoints is a full sentence — noisy as a list title in Swagger UI
    and in generated clients. The slug (== operationId == URL name,
    the versioning key) is the short stable name; the sentence moves
    into ``description`` so nothing is lost.
    """
    schema = _cached_schema()
    schema.info.version = registry.current_version()
    document = schema.convert(skip_validation=True)
    for methods in document.get("paths", {}).values():
        for operation in methods.values():
            if not (isinstance(operation, dict) and "operationId" in operation):
                continue
            summary = operation.get("summary")
            if not summary:
                continue
            if not operation.get("description"):
                operation["description"] = summary
            operation["summary"] = operation["operationId"]
    return document


def versioned_openapi_json(request: HttpRequest) -> HttpResponse:
    """Serve the stored snapshot for ``?api_version=``; live schema otherwise."""

    from django.http import JsonResponse

    from server.apps.apiversions.management.commands.api_snapshot import (
        load_snapshot,
    )

    version = getattr(request, "api_version", None)
    if version is not None and version != registry.current_version():
        snapshot = load_snapshot(version)
        if snapshot is None:
            # Serving the live schema here would silently hand an
            # old-pinned client the NEWEST contract — fail loudly instead
            # (CI's snapshot check should prevent this from ever firing).
            import structlog

            structlog.get_logger("apiversions").error(
                "api_snapshot_missing", version=version
            )
            return JsonResponse(
                {
                    "code": "api_snapshot_missing",
                    "detail": "No committed OpenAPI snapshot for API "
                    f"version {version!r}.",
                },
                status=500,
            )
        return JsonResponse(snapshot, json_dumps_params={"indent": 2}, safe=False)
    return JsonResponse(
        get_openapi_schema(),
        safe=False,
        json_dumps_params={"indent": 2},
    )
