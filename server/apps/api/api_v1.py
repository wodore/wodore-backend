from ninja import NinjaAPI, Swagger

from .parser import MsgSpecParser
from .renderer import MsgSpecRenderer

api = NinjaAPI(
    title="Wodore API", version="1.0.0", docs=Swagger(), renderer=MsgSpecRenderer(), parser=MsgSpecParser(), csrf=True
)

root_path = "server.apps"

api.add_router("/huts", "server.apps.huts.api.router", tags=["hut"])
api.add_router("/organizations/", "server.apps.organizations.api.router", tags=["organization"])
api.add_router("/feedback/", "server.apps.feedbacks.api.router", tags=["feedback"])
