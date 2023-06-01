from ninja import NinjaAPI

api = NinjaAPI()

from ninja import NinjaAPI
from ..organizations.api import router as organizations_router

api = NinjaAPI()

api.add_router("/organizations/", organizations_router, tags=["huts"])