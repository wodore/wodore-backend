import typing as t

from hut_services import LocationSchema, OpenMonthlySchema, TranslationSchema
from ninja import Field, ModelSchema
from pydantic import BaseModel, ConfigDict, field_validator

from django_countries import CountryTuple

from server.apps.owners.models import Owner

# from server.apps.translations import TranslationSchema
# from ..models import Hut, HutType
from ._hut_type import HutTypeSchema

_HUT_FIELDS = (
    "slug",
    "name",
    # "description",
    # "note",
    "review_status",
    "review_comment",
    "is_public",
    "owner",
    "type",
    "elevation",
    "location",
)


class OwnerSchema(ModelSchema):
    name: str | None = Field(..., alias="name_i18n")

    class Meta:
        model = Owner
        fields = ("slug", "name", "url")


class OrganizationDetailSchema(BaseModel):
    slug: str
    name: str
    fullname: str
    link: str
    logo: str
    public: bool
    active: bool
    source_id: str
    # order: int


class OrganizationImageSchema(BaseModel):
    slug: str | None
    name: str | None
    fullname: str | None
    link: str | None
    logo: str | None
    # public: bool
    # active: bool
    # source_id: str


class LicenseInfoSchema(BaseModel):
    """Important information, for example for an image"""

    slug: str
    name: str
    fullname: str
    description: str
    link: str


class ImageMetaAreaSchema(BaseModel):
    x1: float
    x2: float
    y1: float
    x2: float


class ImageMetaSchema(BaseModel):
    crop: ImageMetaAreaSchema | None
    focal: ImageMetaAreaSchema | None
    width: int | None
    height: int | None


class ImageInfoSchema(BaseModel):
    image: str
    image_url: str
    image_meta: ImageMetaSchema
    license: LicenseInfoSchema
    author: str | None
    caption: str | None
    author_url: str | None
    source_url: str | None
    organization: OrganizationImageSchema | None
    attribution: str | None = None
    # tags: list[str]


class HutSchemaOptional(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # name_i18n: str | TranslationSchema | None = None
    slug: str
    name: str | None = Field(..., alias="name_i18n")
    description: str | None = Field(..., alias="description_i18n")
    description_attribution: str
    # description: str | None = Field(None, alias="description_i18n")
    # note: str | None = Field(None, alias="note_i18n")
    owner: OwnerSchema | None = Field(..., alias="hut_owner")
    review_status: str | None = None
    # review_comment: str | None = None
    is_public: bool | None = None
    is_active: bool | None = None
    is_modified: bool | None = None
    type_open: HutTypeSchema | None = Field(None, alias="hut_type_open")
    type_closed: HutTypeSchema | None = Field(None, alias="hut_type_closed")
    elevation: float | None = None
    location: LocationSchema | None = None
    url: str | None = None
    country: CountryTuple | None = None
    capacity_open: int | None = None
    capacity_closed: int | None = None
    sources: list[OrganizationDetailSchema] | None  # = Field(None, alias="orgs")
    photos: str = Field("")
    photos_attribution: str = Field("")
    images: list[ImageInfoSchema] | None
    open_monthly: OpenMonthlySchema | None = None

    @field_validator("country", mode="before")
    @classmethod
    def retrun_country_name(cls, v: t.Any) -> CountryTuple:
        return CountryTuple(code=v.code, name=v.name)

    # class Meta:
    #    model = Hut
    #    fields = _HUT_FIELDS
    #    fields_optional = (f for f in _HUT_FIELDS if f not in ("name"))  # .remove("name")


class HutSchemaDetails(HutSchemaOptional):
    edit_link: str | None = None
    # desc: TranslationSchema | None = None
    translations: t.Any | None = None
