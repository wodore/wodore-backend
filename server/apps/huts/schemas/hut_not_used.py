from typing import Any, List, Optional

from app.models.utils import PydanticType
from app.models.utils.pydantic_type import IntEnum
from core.db.mixins.timestamp_mixin import TimestampMixinSQLModel
from geojson_pydantic import Feature, FeatureCollection
from pydantic import BaseModel, conint, validator
from pydantic.utils import GetterDict
from sqlalchemy import Column
from sqlmodel import JSON, Field, Relationship, SQLModel

from .ref import HutRefLink, HutRefLinkBase
from .utils.hut_fields import (
    Access,
    BookingOccupation,
    Contact,
    HutType,
    Monthly,
    Photo,
    PhotoRead,
    ReviewStatus,
)
from .utils.locale import TranslationModel, Translations

#from typing_extensions import TypedDict
from .utils.point import Elevation, Point, saPoint

NaturalInt = conint(ge=0)


class HutRefProps(BaseModel):
    id:         Optional[str]
    link:       Optional[str]
    name:       Optional[str]
    fullname:   Optional[str]
    logo:       Optional[str]
    icon:       Optional[str]
    color_light:  Optional[str]
    color_dark:   Optional[str]
    ref_url:    Optional[str]
    props:      dict             = Field(default_factory=dict, description="additional properties")

    def update(self, data: dict or "HutRefProps", force:bool=False) -> "HutRefProps":
        if isinstance(data, HutRefProps):
            data = data.dict()
        for k,v in self.validate(data).dict().items():
            if not getattr(self, k, None) or force:
                try:
                    setattr(self, k, v)
                except AttributeError:
                    pass # ignore value
        return self

    class Config:
        orm_mode = True

# TODO --> needs to be in locale.py
class Translator(GetterDict):

    def get(self, key: str, default: Any) -> Any:

        val = getattr(self._obj, key)
        #rprint(f"Get key: {key}: {type(val)}")
        if isinstance(val, Translations.TransField):
            field = getattr(self._obj, key.field)
            val = getattr(self._obj, field, Translations()).get()
        #if isinstance(val, Translations) or key == "name":
        if getattr(self._obj, f"{key}_t", None):
            #rprint(f"Got translation: {key}")
            #key_t = key.replace(key, "_t")
            key_t = key + "_t"
            val = getattr(self._obj, key_t).get()
            #rprint(value)
            #setattr(self, key, value )
        return val

class HutReadBase(BaseModel):
    #@root_validator(pre=True)
    #def translate_name(cls, values):
    #    rprint("ROOT Validator:")
    #    rprint(values)
    #    for key, val in values.items():
    #        if isinstance(val, Translations.TransField):
    #            values[key] = values.get(values[key].field, None)
    #        if isinstance(val, Translations):
    #            key_t = key.replace(key, "_t")
    #            if key_t not in values.keys():
    #                values[key_t] = val
    #    return values

    name:       Optional[str]
    slug:       Optional[str]
    type_id:      HutType = 0 # what type: caping, alpine, biwak ..

    class Config:
        getter_dict = Translator

class HutReadRefs(BaseModel):
    refs:       dict[str, HutRefProps] = Field(default_factory=dict)
    @validator('refs', pre=True)
    def list_to_ref_dict(cls, refs):
        if isinstance(refs, list):
            ref_d = {}
            for ref in refs:
                if ref.is_active:
                    ref_link = ref.ref_link
                    link_props = HutRefProps.from_orm(ref)
                    link_props.link = ref.url
                    link_props.update(ref_link)
                    ref_d[ref.slug] = link_props
            return ref_d
        return refs

class HutReadPhotos(BaseModel):
    photos:     Optional[List[PhotoRead]]
    @validator('photos', pre=True)
    def photos_to_read(cls, photos:List[Photo]) -> List[PhotoRead]:
        out = []
        for p in photos:
            if isinstance(p, Photo):
                out.append(p.to_read())
            else:
                out.append(p)
        return out

class HutGeoReadBasic(HutReadBase):

    class Config:
        orm_mode = True


class HutGeoRead(HutReadBase, HutReadRefs, HutReadPhotos):
    url:        Optional[str]
    owner:      Optional[str]
    booking:    List[BookingOccupation] = []

    elevation:  Optional[Elevation]
    capacity:   Optional[NaturalInt]
    capacity_shelter: Optional[NaturalInt]

    class Config:
        orm_mode = True

class HutFeature(Feature):
    properties: HutGeoRead

class HutFeatureCollection(FeatureCollection):
    features: List[HutFeature]

#class HutBase(SQLModel):
class HutBase(BaseModel):

    #name_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
    #_name_t               = Translations.get_validator('name_t')

    slug:        Optional[str] = Field(unique=True, schema_extra={"example": "sac-bergen"}, max_length=40)

    #description_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
    #_description_t               = Translations.get_validator('description_t')
    owner:       Optional[str] = Field(None, max_length=100)
    # adress stuff
    contacts:     List[Contact] = Field(default_factory=list, max_items=8, sa_column=Column(PydanticType(List[Contact])))
    url:         Optional[str] = Field(None, max_length=200)
    comment:     Optional[str] = Field(None, max_length=2000)#, sa_column=Column(VARCHAR(1000)))

    photos:        List[Photo] = Field(default_factory=list, sa_column=Column(PydanticType(List[Photo])))

    country :              str = Field("CH", max_length=10)
    point:               Point = Field(..., sa_column=Column(saPoint, nullable=False))
    elevation:   Optional[Elevation] = Field(None, index=True)
    # hut stuff
    capacity:          Optional[NaturalInt] = Field(default=0, index=True)
    capacity_shelter:  Optional[NaturalInt] = Field(default=0, index=True)

    infrastructure:       dict = Field(default_factory=dict, sa_column=Column(JSON)) # TODO, better name. Maybe use infra and service separated, external table
    access:             Access = Field(default_factory=Access, sa_column=Access.get_sa_column())


    review_status: ReviewStatus = ReviewStatus.new
    is_active:             bool = Field(default=True, index=True)

    monthly:            Monthly = Field(default_factory=Monthly, sa_column=Monthly.get_sa_column())
    type_id:      HutType =  Field(0, sa_column=Column(IntEnum(HutType)))

    def get_geojson(self, model:HutGeoReadBasic=HutGeoRead) -> HutFeature:
        point = self.point.geojson
        props = model.from_orm(self)
        if not props.name:
            props.name = self.name_t._
        return Feature(geometry=point, properties=props, id=self.id, type="Feature")


    class Config:
        orm_mode = True

class HutBaseT(HutBase, TranslationModel):
    """Hut base with translations"""

    name_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
    _name_t               = Translations.get_validator('name_t')

    description_t: Translations  = Field(Translations(), sa_column=Column(PydanticType(Translations)))
    _description_t               = Translations.get_validator('description_t')

class Hut(HutBaseT):
    """Main hut model"""
    #test_name: str             = Translations.Field(field="test_name_t")
    name: Optional[str]   = Translations.TransField(field="name_t")
    description: Optional[str]   = Translations.TransField(field="description_t")
    refs: List[HutRefLinkBase] = []


class HutDatabase(HutBaseT, TimestampMixinSQLModel, SQLModel, table=True):
    """Hut model used for the database"""
    __tablename__: str = "hut"
    id: Optional[int] = Field(default=None, primary_key=True)
    refs: List[HutRefLink] = Relationship(back_populates="hut_link")#, sa_relationship_kwargs={"lazy": "selectin"})


class HutRead(HutReadBase, HutReadRefs, HutReadPhotos, HutBase):
    """Main hut model"""
    #name: Optional[str]#   = Translations.Field(field="name_t")
    description: Optional[str]
    ##refs: List[HutRefLinkBase] = []
    ##refs: HutProps = []
    #refs:       dict[str, HutRefProps] = Field(default_factory=dict)
    #@validator('refs', pre=True)
    #def list_to_ref_dict(cls, refs):
    #    if isinstance(refs, list):
    #        ref_d = {}
    #        for ref in refs:
    #            if ref.is_active:
    #                ref_link = ref.ref_link
    #                link_props = HutRefProps.from_orm(ref)
    #                link_props.link = ref.url
    #                link_props.update(ref_link)
    #                link_props.ref_url = ref_link.url
    #                ref_d[ref.slug] = link_props
    #        return ref_d
    #    return refs
