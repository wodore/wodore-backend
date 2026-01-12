import typing as t
from enum import Enum

from ninja import Field, ModelSchema, Schema

from server.apps.symbols.utils import resolve_symbol_url

from .models import Category


class MediaUrlModeEnum(str, Enum):
    """Media URL mode for image fields."""

    no = "no"  # Exclude media fields
    relative = "relative"  # Return relative paths (e.g., /media/...)
    absolute = "absolute"  # Return absolute URLs (e.g., http://...)


class CategorySchema(ModelSchema):
    """Basic category schema with essential fields."""

    slug: str
    name: str = Field(..., alias="name_i18n")
    description: str = Field("", alias="description_i18n")
    order: int
    level: int | None = Field(
        None, description="Hierarchy level (0=root, 1=child, etc.)"
    )

    # Image URLs (now using new Symbol FK fields)
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None

    # Parent reference
    parent_slug: str | None = Field(None, description="Parent category slug")

    @staticmethod
    def resolve_symbol_detailed(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for detailed symbol from new Symbol app."""
        return resolve_symbol_url(obj, context, "detailed")

    @staticmethod
    def resolve_symbol_simple(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for simple symbol from new Symbol app."""
        return resolve_symbol_url(obj, context, "simple")

    @staticmethod
    def resolve_symbol_mono(obj: Category, context: dict[str, t.Any]) -> str | None:
        """Resolve absolute URL for monochrome symbol from new Symbol app."""
        return resolve_symbol_url(obj, context, "mono")

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
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
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


class CategoryTreeSchema(Schema):
    """Hierarchical tree representation of categories."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")

    # Optional media fields
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None

    children: list["CategoryTreeSchema"] | bool = False


class CategoryListItemSchema(Schema):
    """Simple category item for list view."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")
    children: bool  # Whether this category has children

    # Optional media fields
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None


class CategoryMapSchema(Schema):
    """Category with children for map view."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")
    children_count: int  # Number of direct children

    # Optional media fields
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None

    # Children as dict mapping
    children: dict[str, "CategoryMapSchema"] = {}
