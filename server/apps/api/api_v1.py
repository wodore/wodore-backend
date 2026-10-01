from ninja import NinjaAPI

from server.apps.apiversions import registry
from server.apps.apiversions.docs import VersionedSwagger
from server.apps.apiversions.renderer import VersionedRenderer

from .parser import MsgSpecParser

# TODO: check csrf: https://django-ninja.dev/reference/csrf/
api = NinjaAPI(
    title="Wodore API",
    version=registry.current_version(),  # OpenAPI info.version = API version
    description=(
        "Clients pin a contract version with the `Api-Version` header or the "
        "`api_version` query parameter (e.g. `2026-10-01`); no version given "
        "serves the latest. Deprecated versions are announced via "
        "`Deprecation`/`Sunset` headers; see `/v1/version` for supported "
        "versions and `/CHANGELOG_API.md` (repo) for the API changelog."
    ),
    docs=VersionedSwagger(),
    renderer=VersionedRenderer(),
    parser=MsgSpecParser(),
)

root_path = "server.apps"

# Add routers from most specific to least specific to avoid conflicts
api.add_router(
    "/geo/images/", "server.apps.geometries.api_images.router", tags=["geoimages"]
)
api.add_router("/geo/", "server.apps.geometries.api.router", tags=["geometries"])
api.add_router("/categories/", "server.apps.categories.api.router", tags=["category"])
api.add_router("/huts", "server.apps.huts.api.router", tags=["hut"])
api.add_router("/meteo/", "server.apps.meteo.api.router", tags=["meteo"])
api.add_router(
    "/organizations/", "server.apps.organizations.api.router", tags=["organization"]
)
api.add_router("/symbols/", "server.apps.symbols.api.router", tags=["symbols"])
api.add_router("/feedback/", "server.apps.feedbacks.api.router", tags=["feedback"])
api.add_router("/", "server.apps.utils.api.router", tags=["utils"])

# Versioning wiring — must run after the last add_router (stashes
# request.ninja_operation per operation and guards endpoint sunsets).
from server.apps.apiversions.wrap import wrap_api

wrap_api(api)


def versioned_openapi_json(request):
    """Serve the stored snapshot for `?api_version=`; live schema otherwise.

    Shadowing ninja's own openapi.json route from server/urls.py (exact path
    wins over the /v1/ include) so no ninja internals are overridden.
    """

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
    # Live schema — enforce info.version from the registry (the NinjaAPI
    # ``version`` attribute is frozen at import time; tests may import this
    # module while a temporary registry entry exists).
    from ninja.responses import NinjaJSONEncoder

    schema = api.get_openapi_schema()
    schema["info"]["version"] = registry.current_version()
    return JsonResponse(
        schema, encoder=NinjaJSONEncoder, safe=False, json_dumps_params={"indent": 2}
    )
