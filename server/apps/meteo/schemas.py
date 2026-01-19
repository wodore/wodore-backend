from enum import Enum

from ninja import ModelSchema
from pydantic import BaseModel

from .models import WeatherCode


class IncludeModeEnum(str, Enum):
    """Include mode for nested objects - controls level of detail."""

    no = "no"
    slug = "slug"
    all = "all"


class SymbolStyleEnum(str, Enum):
    """Symbol style variants."""

    detailed = "detailed"
    simple = "simple"
    mono = "mono"


class DayTimeEnum(str, Enum):
    """Day/night time options."""

    day = "day"
    night = "night"


class WeatherCodeSchema(ModelSchema):
    """Schema for WeatherCode model - returns all fields."""

    class Meta:
        model = WeatherCode
        fields = "__all__"
        fields_optional = "__all__"


class WeatherCodeOptional(ModelSchema):
    """Schema for WeatherCode model with all fields optional."""

    class Meta:
        model = WeatherCode
        fields = "__all__"
        fields_optional = "__all__"


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
