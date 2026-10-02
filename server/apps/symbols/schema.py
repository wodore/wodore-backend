"""Pydantic API schemas for symbols (plain models, dmr-compatible)."""

import pydantic
from pydantic import BaseModel, field_validator


class SymbolURLSchema(BaseModel):
    """Schema for symbol URLs with three style variants."""

    detailed: str | None = None
    simple: str | None = None
    mono: str | None = None


class SymbolOptional(pydantic.BaseModel):
    """Symbol with every field optional (include/exclude base)."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    id: str | None = None
    slug: str | None = None
    style: str | None = None
    svg_file: str | None = None
    search_text: str | None = None
    license: int | None = None
    author: str | None = None
    author_url: str | None = None
    source_url: str | None = None
    source_org: int | None = None
    is_active: bool | None = None

    @field_validator("svg_file", mode="before")
    @classmethod
    def _svg_to_str(cls, value: object) -> str | None:
        """ImageFieldFile -> path string (former ninja ModelSchema coercion)."""
        return str(value) if value else None

    @field_validator("id", mode="before")
    @classmethod
    def _uuid_to_str(cls, value: object) -> str | None:
        """UUID -> string (former ninja ModelSchema coercion)."""
        return str(value) if value is not None else None

    @field_validator("license", "source_org", mode="before")
    @classmethod
    def _fk_to_pk(cls, value: object) -> int | None:
        """FK instance -> pk int (ninja mapped FK fields to their attname)."""
        if value is None:
            return None
        return getattr(value, "pk", value)
