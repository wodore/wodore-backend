from typing import Optional

# import phonenumbers
# from app.models.ref import HutRefLink
from pydantic import BaseModel, Field

# from app.models.utils.locale import Translations
# from ..utils.hut_fields import Contact, Monthly, MonthlyOptions, Open, Catering
# from core.db.mixins.timestamp_mixin import TimestampMixinSQLModel
# from typing_extensions import TypedDict
# from .point import Elevation, Latitude, Longitude, Point
from .point import Point

# from sqlmodel import Field, SQLModel
# from pydantic_computed import Computed, computed
# from ..hut import Hut
# from ..utils.hut_fields import HutType



class HutSchema(BaseModel):
    """Hut schema"""

    slug: Optional[str] = None
    name: dict[str, str]
    description: dict[str, str] = Field(dict(), max_length=2000)  # , sa_column=Column(VARCHAR(1000)))
    point: Point
    elevation: Optional[float] = None
    is_active: bool = True

    # owner:       Optional[str] = Field(None, max_length=100)
    ##contacts:     List[Contact] = Field(default_factory=list, max_items=8, sa_column=Column(PydanticType(List[Contact])))
    url: str = Field("", max_length=200)
    note: dict[str, str] = Field(dict(), max_length=2000)  # , sa_column=Column(VARCHAR(1000)))

    ##photos:        List[Photo] = Field(default_factory=list, sa_column=Column(PydanticType(List[Photo])))

    ##country :              str = Field("CH", max_length=10)
    ## hut stuff
    country: str = "CH"
    capacity: Optional[int] = None
    capacity_shelter: Optional[int] = None
    type: Optional[str] = None

    props: dict[str, str] = Field(dict())  # Property field, depends ond organization and hut
