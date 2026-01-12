import typing as t

from ninja import Field, ModelSchema

from server.apps.symbols.utils import resolve_symbol_urls


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
    symbol: dict[str, str | None] | None = None

    @staticmethod
    def resolve_symbol(
        obj: Category, context: dict[str, t.Any]
    ) -> dict[str, str | None] | None:
        """Resolve symbol URLs from new Symbol FK fields."""
        return resolve_symbol_urls(obj, context)

    class Meta:
        model = Category
        fields = (
            "order",
            "slug",
            "name",
        )
