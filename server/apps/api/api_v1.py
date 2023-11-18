from ninja import NinjaAPI, Swagger

from ..organizations.api import router as organizations_router

from .parser import MsgSpecParser
from .renderer import MsgSpecRenderer

api = NinjaAPI()


api = NinjaAPI(docs=Swagger(), renderer=MsgSpecRenderer(), parser=MsgSpecParser())

root_path = "server.apps"

# api.add_router("/organizations/", organizations_router, tags=["huts"])
api.add_router("/organizations/", f"{root_path}.organizations.api.router", tags=["huts"])
