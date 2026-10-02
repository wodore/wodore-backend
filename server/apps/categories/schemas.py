"""Pydantic API schemas for categories (plain models, dmr-compatible).

The tree/list/map endpoints build plain dicts in the handlers; these
schemas document the response shape and validate it in dev/test.
"""

from enum import Enum

import pydantic


class MediaUrlModeEnum(str, Enum):
    """Media URL mode for image fields."""

    no = "no"  # Exclude media fields
    relative = "relative"  # Return relative paths (e.g., /media/...)
    absolute = "absolute"  # Return absolute URLs (e.g., http://...)


class SymbolVariantEnum(str, Enum):
    """Symbol variant types for categories."""

    detailed = "detailed"
    simple = "simple"
    mono = "mono"


class CategoryTreeSchema(pydantic.BaseModel):
    """Hierarchical tree representation of categories."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")
    color: str  # Theme color as hex (e.g., "#4B8E43")

    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None

    children: list["CategoryTreeSchema"] | bool = False


class CategoryListItemSchema(pydantic.BaseModel):
    """Simple category item for list view."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")
    color: str  # Theme color as hex (e.g., "#4B8E43")
    children: bool  # Whether this category has children

    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None


class CategoryMapSchema(pydantic.BaseModel):
    """Category with children for map view."""

    slug: str
    name: str
    description: str = ""
    order: int
    level: int
    parent: str | None = None  # Parent slug
    identifier: str  # Full path identifier (e.g., "map.accommodation.hut")
    color: str  # Theme color as hex (e.g., "#4B8E43")
    children_count: int  # Number of direct children

    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None

    children: dict[str, "CategoryMapSchema"] = {}


CategoryTreeSchema.model_rebuild()
CategoryMapSchema.model_rebuild()
