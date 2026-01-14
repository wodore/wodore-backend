import typing as t
from datetime import datetime

from hut_services import LocationSchema, OpenMonthlySchema
from ninja import Field, ModelSchema
from pydantic import (
    BaseModel,
    ConfigDict,
    computed_field,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from django_countries import CountryTuple

from django.conf import settings

from server.apps.images.transfomer import ImagorImage
from server.apps.owners.models import Owner

# from server.apps.translations import TranslationSchema
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


class OrganizationBaseSchema(BaseModel):
    slug: str
    name: str
    fullname: str
    link: str
    logo: str
    public: bool
    source_id: str


class OrganizationDetailSchema(OrganizationBaseSchema):
    active: bool
    order: int


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
    name: str | None
    fullname: str | None
    description: str | None = None
    link: str | None = None


class ImageMetaAreaSchema(BaseModel):
    x1: float
    x2: float
    y1: float
    y2: float


class ImageMetaSchema(BaseModel):
    crop: ImageMetaAreaSchema | None = None
    focal: ImageMetaAreaSchema | None = None
    width: int | None = None
    height: int | None = None


class TransformImageConfig(BaseModel):
    name: str = Field(
        default=None,
        description="Name of the transformed image, per default '{width}x{height}'",
    )
    width: int
    height: int
    radius: int
    quality: int | None = None
    blur: float | None = None
    use_focal: bool = True
    crop_to_focal: bool = False
    focal: ImageMetaAreaSchema | None = Field(
        default=None, description="Focal point, if not supplied takes the default one"
    )
    crop: ImageMetaAreaSchema | None = Field(default=None, description="Crop area")

    @model_validator(mode="after")
    def set_name(self) -> Self:
        if self.name is None:
            self.name = f"{self.width}x{self.height}"
        return self


class ImageInfoSchema(BaseModel):
    image: str
    # image_url: str
    image_meta: ImageMetaSchema
    license: LicenseInfoSchema
    author: str | None = None
    caption: str | None = None
    author_url: str | None = None
    source_url: str | None = None
    organization: OrganizationImageSchema | None = None
    attribution: str | None = None
    _urls: t.Sequence[TransformImageConfig] | None = None
    # tags: list[str]

    def get_image_configs(self) -> t.Sequence[TransformImageConfig]:
        if self._urls is None:
            return [
                TransformImageConfig(name="avatar", width=180, height=180, radius=90),
                TransformImageConfig(name="thumb", width=250, height=200, radius=0),
                TransformImageConfig(name="preview", width=600, height=400, radius=0),
                TransformImageConfig(
                    name="preview-placeholder",
                    width=300,
                    height=200,
                    radius=0,
                    quality=5,
                    blur=3,
                ),
                TransformImageConfig(name="medium", width=1000, height=800, radius=0),
                TransformImageConfig(name="large", width=1800, height=1200, radius=0),
            ]
        return self._urls

    def add_image_config(
        self,
        name: str | None,
        width: int | None,
        height: int | None,
        radius: int = 0,
        config: TransformImageConfig | None = None,
    ) -> t.Sequence[TransformImageConfig]:
        if config is None:
            assert_msg = "name, width and height must be provided if config is None"
            assert name is not None, assert_msg
            assert height is not None, assert_msg
            assert width is not None, assert_msg
            config = TransformImageConfig(
                name=name, width=width, height=height, radius=radius
            )
        self.set_image_configs([*self.get_image_configs(), config])
        return self.get_image_configs()

    def set_image_configs(
        self, configs: t.Sequence[TransformImageConfig]
    ) -> t.Sequence[TransformImageConfig]:
        self._urls = configs
        return self.get_image_configs()

    @computed_field
    @property
    def urls(self) -> dict[str, str]:
        """
        Return the image URL with the transformations applied.
        """
        img_urls = {}
        for cfg in self.get_image_configs():
            try:
                if cfg.focal is not None:
                    focal = cfg.focal
                else:
                    focal = (
                        self.image_meta.focal
                        if self.image_meta and cfg.use_focal
                        else None
                    )
                crop_start = None
                crop_stop = None
                focal_str = None
                if focal:
                    focal_str = f"{focal.x1}x{focal.y1}:{focal.x2}x{focal.y2}"
                    if not cfg.crop_to_focal:
                        crop_start, crop_stop = focal_str.split(":")
                if cfg.crop is not None:
                    crop_start, crop_stop = (
                        f"{cfg.crop.x1}x{cfg.crop.y1}",
                        f"{cfg.crop.x2}x{cfg.crop.y2}",
                    )
                image_url = (
                    self.image
                    if self.image.startswith("http")
                    else f"{settings.MEDIA_URL}/{self.image}"
                )
                img = (
                    ImagorImage(image_url)
                    .transform(
                        size=f"{cfg.width}x{cfg.height}",
                        focal=focal_str,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        round_corner=cfg.radius,
                        quality=cfg.quality,
                        blur=cfg.blur,
                    )
                    .get_full_url()
                )
                img_urls[cfg.name] = img
            except Exception as e:
                print(e)
                img = "Missing"
        return img_urls


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
    sources: list[OrganizationBaseSchema] | None  # = Field(None, alias="orgs")
    photos: str = Field("")
    photos_attribution: str = Field("")
    images: list[ImageInfoSchema] | None
    open_monthly: OpenMonthlySchema | None = None
    has_availability: bool | None = None
    availability_source: str | None = Field(None, alias="availability_source_ref__slug")

    @field_validator("country", mode="before")
    @classmethod
    def retrun_country_name(cls, v: t.Any) -> CountryTuple:
        return CountryTuple(code=v.code, name=v.name)

    # class Meta:
    #    model = Hut
    #    fields = _HUT_FIELDS
    #    fields_optional = (f for f in _HUT_FIELDS if f not in ("name"))  # .remove("name")


class HutSchemaList(HutSchemaOptional):
    """Schema for hut list endpoints (without created/modified timestamps)."""

    pass


class HutSchemaDetails(HutSchemaOptional):
    """Schema for single hut detail endpoint (with all details including timestamps)."""

    edit_link: str | None = None
    # desc: TranslationSchema | None = None
    translations: t.Any | None = None
    created: datetime | None = None
    modified: datetime | None = None


class HutTypeSimpleSchema(BaseModel):
    """Simplified hut type schema for search results."""

    open: str | None = None
    closed: str | None = None


class CapacitySimpleSchema(BaseModel):
    """Simplified capacity schema for search results."""

    open: int | None = None
    closed: int | None = None


class HutSearchResultSchema(BaseModel):
    """Simplified schema for hut search results - optimized for fast autocomplete."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    slug: str
    hut_type: t.Any = None  # Can be None, HutTypeSimpleSchema, or full HutTypeSchema
    capacity: CapacitySimpleSchema
    location: LocationSchema
    elevation: float | None = None
    avatar: str | None = None  # Full URL to avatar image
    score: float  # Search relevance score
    sources: t.Any = (
        None  # Can be None, list[str] (slugs), or list[OrganizationBaseSchema]
    )
