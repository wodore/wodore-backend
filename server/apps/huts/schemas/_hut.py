import typing as t

from hut_services import LocationSchema
from ninja import Field, ModelSchema
from pydantic import BaseModel, ConfigDict, field_validator

from django_countries import CountryTuple
from server.apps.organizations.models import Organization

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


class HutSchemaOptional(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # name_i18n: str | TranslationSchema | None = None
    slug: str
    name: str | None = Field(..., alias="name_i18n")
    description: str | None = Field(..., alias="description_i18n")
    # description: str | None = Field(None, alias="description_i18n")
    # note: str | None = Field(None, alias="note_i18n")
    owner: OwnerSchema | None = Field(..., alias="hut_owner")
    review_status: str | None = None
    # review_comment: str | None = None
    is_public: bool | None = None
    type_open: HutTypeSchema | None = Field(None, alias="hut_type_open")
    type_closed: HutTypeSchema | None = Field(None, alias="hut_type_closed")
    elevation: float | None = None
    location: LocationSchema | None = None
    url: str | None = None
    country: CountryTuple | None = None
    capacity_open: int | None = None
    capacity_closed: int | None = None
    organizations: list[OrganizationDetailSchema] | None = Field(None, alias="orgs")
    photo: str = Field("")

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
