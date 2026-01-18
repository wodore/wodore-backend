from ninja import NinjaAPI, Swagger

from .parser import MsgSpecParser
from .renderer import MsgSpecRenderer

# TODO: check csrf: https://django-ninja.dev/reference/csrf/
api = NinjaAPI(
    title="Wodore API",
    version="1.0.0",
    docs=Swagger(),
    renderer=MsgSpecRenderer(),
    parser=MsgSpecParser(),
)

root_path = "server.apps"

# Add routers from most specific to least specific to avoid conflicts
api.add_router("/geo/places/", "server.apps.geometries.api.router", tags=["geometries"])
api.add_router("/categories/", "server.apps.categories.api.router", tags=["category"])
api.add_router("/huts", "server.apps.huts.api.router", tags=["hut"])
api.add_router("/meteo/", "server.apps.meteo.api.router", tags=["meteo"])
api.add_router(
    "/organizations/", "server.apps.organizations.api.router", tags=["organization"]
)
api.add_router("/symbols/", "server.apps.symbols.api.router", tags=["symbols"])
api.add_router("/feedback/", "server.apps.feedbacks.api.router", tags=["feedback"])
api.add_router("/", "server.apps.utils.api.router", tags=["utils"])
