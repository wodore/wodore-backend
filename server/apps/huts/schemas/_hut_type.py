import typing as t

from ninja import Field, ModelSchema

from django.conf import settings

from server.apps.categories.models import Category

# Note: HutType is now a helper class, these schemas use Category model
# The API still references "hut_type" for backward compatibility


class HutTypeDetailSchema(ModelSchema):
    slug: str
    name: str = Field(..., alias="name_i18n")
    description: str = Field("", alias="description_i18n")
    order: int | None = Field(None, alias="order")
    # filter_on: bool = True
    # symbol: str | None

    class Meta:
        model = Category
        fields = (
            "slug",
            "name",
            "symbol_detailed",
            "description",
            "order",
            "symbol_simple",
            "symbol_mono",
        )
        fields_optional = (
            "name",
            "description",
            "order",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        )


class HutTypeSchema(ModelSchema):
    # model_config = ConfigDict(from_attributes=True)
    order: int | None = Field(None, alias="order")
    slug: str
    name: str | None = Field(..., alias="name_i18n")
    symbol: str | None
    symbol_simple: str | None
    icon: str | None

    @staticmethod
    def resolve_symbol(obj: Category, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol_detailed}"

    @staticmethod
    def resolve_symbol_simple(obj: Category, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol_simple}"

    @staticmethod
    def resolve_icon(obj: Category, context: dict[str, t.Any]) -> str:
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol_mono}"

    class Meta:
        model = Category
        fields = (
            "order",
            "slug",
            "name",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        )
