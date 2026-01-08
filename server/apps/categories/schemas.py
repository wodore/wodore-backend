import typing as t

from ninja import Field, ModelSchema

from django.conf import settings

from .models import Category


class CategorySchema(ModelSchema):
    """Basic category schema with essential fields."""

    slug: str
    name: str = Field(..., alias="name_i18n")
    description: str = Field("", alias="description_i18n")
    order: int
    level: int | None = Field(
        None, description="Hierarchy level (0=root, 1=child, etc.)"
    )

    # Image URLs
    symbol: str | None = None
    symbol_simple: str | None = None
    icon: str | None = None

    # Parent reference
    parent_slug: str | None = Field(None, description="Parent category slug")

    @staticmethod
    def resolve_symbol(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for detailed symbol."""
        if not obj.symbol:
            return None
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol}"

    @staticmethod
    def resolve_symbol_simple(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for simple symbol."""
        if not obj.symbol_simple:
            return None
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.symbol_simple}"

    @staticmethod
    def resolve_icon(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for icon."""
        if not obj.icon:
            return None
        request = context["request"]
        media_url = request.build_absolute_uri(settings.MEDIA_URL)
        return f"{media_url}{obj.icon}"

    @staticmethod
    def resolve_level(obj: Category) -> int:
        """Calculate hierarchy level."""
        return obj.get_level()

    @staticmethod
    def resolve_parent_slug(obj: Category) -> str | None:
        """Get parent slug if exists."""
        return obj.parent.slug if obj.parent else None

    class Meta:
        model = Category
        fields = (
            "slug",
            "name",
            "description",
            "order",
            "symbol",
            "symbol_simple",
            "icon",
        )


class CategoryDetailSchema(CategorySchema):
    """Detailed category schema with additional fields."""

    is_active: bool

    # Default child reference
    default_slug: str | None = Field(None, description="Default child category slug")

    # Children (for hierarchy display)
    children: list["CategorySchema"] = Field([], description="Child categories")

    @staticmethod
    def resolve_default_slug(obj: Category) -> str | None:
        """Get default child slug if exists."""
        return obj.default.slug if obj.default else None

    @staticmethod
    def resolve_children(obj: Category, context: dict[str, t.Any]) -> list[dict]:
        """Get active children categories."""

        children = obj.children.filter(is_active=True).order_by("order", "slug")
        # Recursively convert children to schema format
        result = []
        for child in children:
            result.append(CategorySchema.from_orm(child, context=context))
        return result

    class Meta:
        model = Category
        fields = CategorySchema.Meta.fields + ("is_active",)


class CategoryTreeSchema(ModelSchema):
    """Hierarchical tree representation of categories."""

    slug: str
    name: str = Field(..., alias="name_i18n")
    order: int
    level: int
    children: list["CategoryTreeSchema"] = []

    @staticmethod
    def resolve_level(obj: Category) -> int:
        return obj.get_level()

    class Meta:
        model = Category
        fields = ("slug", "name", "order")
