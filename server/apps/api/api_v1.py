from ninja import NinjaAPI, Swagger

from .parser import MsgSpecParser
from .renderer import MsgSpecRenderer


api = NinjaAPI(title="Wodore API", version="1.0.0", docs=Swagger(), renderer=MsgSpecRenderer(), parser=MsgSpecParser())

root_path = "server.apps"

# api.add_router("/organizations/", organizations_router, tags=["huts"])
api.add_router("/organizations/", f"organizations.api.router", tags=["huts"])
