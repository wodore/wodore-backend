from enum import Enum

from pydantic import BaseModel

from server.apps.api.enums import IncludeModeEnum

__all__ = ["DayTimeEnum", "IncludeModeEnum", "SymbolStyleEnum"]


class SymbolStyleEnum(str, Enum):
    """Symbol style variants."""

    detailed = "detailed"
    simple = "simple"
    mono = "mono"


class DayTimeEnum(str, Enum):
    """Day/night time options."""

    day = "day"
    night = "night"


class SymbolURLSchema(BaseModel):
    """Schema for symbol URLs with three style variants."""

    detailed: str | None = None
    simple: str | None = None
    mono: str | None = None


class CategoryRefSchema(BaseModel):
    """Minimal category reference."""

    slug: str
    name: str | None = None
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None


class OrganizationRefSchema(BaseModel):
    """Minimal organization reference."""

    slug: str
    name: str | None = None
    fullname: str | None = None
