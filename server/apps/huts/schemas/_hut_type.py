import typing as t  # noqa: F401

from ninja import Field, ModelSchema

# from pydantic import BaseModel, ConfigDict, field_validator
# from server.apps.translations import TranslationSchema
from ..models import HutType


class HutTypeDetailSchema(ModelSchema):
    slug: str
    name: str = Field(..., alias="name_i18n")
    description: str = Field("", alias="description_i18n")
    # symbol: str | None

    class Meta:
        model = HutType
        fields = HutType.FIELDS
        fields_optional = (h for h in HutType.FIELDS if h not in ("slug",))


class HutTypeSchema(ModelSchema):
    slug: str
    name: str | None = Field(..., alias="name_i18n")
    symbol: str | None

    class Meta:
        model = HutType
        fields = ("slug", "name", "symbol")
