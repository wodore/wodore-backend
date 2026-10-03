"""Typed response schema for the weather-codes endpoint."""

import pydantic


class SymbolValue(pydantic.BaseModel):
    """One symbol variant (day or night)."""

    slug: str | None = None
    url: str | None = None


class CategoryValue(pydantic.BaseModel):
    """The weather-code category."""

    slug: str | None = None
    name: str | None = None
    parent: str | None = None
    symbol_detailed: str | None = None
    symbol_simple: str | None = None
    symbol_mono: str | None = None


class CollectionValue(pydantic.BaseModel):
    """The symbol collection a weather code belongs to."""

    slug: str | None = None
    organization: str | None = None


class WeatherCodeValue(pydantic.BaseModel):
    """One weather-code entry (the value in the WMO-keyed dict)."""

    model_config = pydantic.ConfigDict(extra="allow")

    code: int
    slug: str
    description_day: str | None = None
    description_night: str | None = None
    symbol_day: SymbolValue | None = None
    symbol_night: SymbolValue | None = None
    category: CategoryValue | None = None
    collection: CollectionValue | None = None


class WeatherCodesDict(pydantic.RootModel[dict[int, WeatherCodeValue]]):
    """Response model: dict keyed by WMO code."""
