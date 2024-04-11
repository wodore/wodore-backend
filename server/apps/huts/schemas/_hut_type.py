import typing as t

from ninja import Field, ModelSchema
from pydantic import ConfigDict

from django.conf import settings  # noqa: F401

# from server.apps.translations import TranslationSchema
from ..models import HutType


class HutTypeDetailSchema(ModelSchema):
    slug: str
    name: str = Field(..., alias="name_i18n")
    description: str = Field("", alias="description_i18n")
    # filter_on: bool = True
    # symbol: str | None

    class Meta:
        model = HutType
        fields = HutType.FIELDS
        fields_optional = (h for h in HutType.FIELDS if h not in ("slug",))


class HutTypeSchema(ModelSchema):
    # model_config = ConfigDict(from_attributes=True)
    level: int | None = None
    slug: str
    name: str | None = Field(..., alias="name_i18n")
    symbol: str | None
    symbol_simple: str | None
    icon: str | None

    @staticmethod
    def resolve_symbol(obj: HutType, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol}"

    @staticmethod
    def resolve_symbol_simple(obj: HutType, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol_simple}"

    @staticmethod
    def resolve_icon(obj: HutType, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.icon}"

    class Meta:
        model = HutType
        fields = ("level", "slug", "name", "symbol")
