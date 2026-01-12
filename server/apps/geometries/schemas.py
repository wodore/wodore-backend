"""
Schemas for GeoPlace API endpoints.
"""

from typing import Any

from django.conf import settings
from django.http import HttpRequest
from hut_services import LocationSchema
from ninja import Field, ModelSchema, Schema

from server.apps.categories.models import Category
from server.apps.organizations.schema import (
    OrganizationSourceIdDetailSchema,
    OrganizationSourceIdSlugSchema,
)


class SymbolSchema(Schema):
    """Schema for symbol URLs with different variants."""

    simple: str | None = None
    detailed: str | None = None
    mono: str | None = None

    @staticmethod
    def resolve_simple(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get simple symbol URL."""
        if not hasattr(obj, "symbol_simple") or not obj.symbol_simple:
            return None
        path = str(obj.symbol_simple)
        if path.startswith("http"):
            return path
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if request and not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)
        return f"{media_url}{path}"

    @staticmethod
    def resolve_detailed(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get detailed symbol URL."""
        if not hasattr(obj, "symbol_detailed") or not obj.symbol_detailed:
            return None
        path = str(obj.symbol_detailed)
        if path.startswith("http"):
            return path
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if request and not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)
        return f"{media_url}{path}"

    @staticmethod
    def resolve_mono(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get mono symbol URL."""
        if not hasattr(obj, "symbol_mono") or not obj.symbol_mono:
            return None
        path = str(obj.symbol_mono)
        if path.startswith("http"):
            return path
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if request and not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)
        return f"{media_url}{path}"


class CategorySchema(ModelSchema):
    """Schema for category information in GeoPlace responses."""

    name: str | None = Field(..., alias="name_i18n")
    description: str | None = Field(None, alias="description_i18n")
    symbol: SymbolSchema | None = None

    class Meta:
        model = Category
        fields = ("slug", "name", "description")


class GeoPlaceBaseSchema(Schema):
    """Base schema for GeoPlace with common fields."""

    id: int
    name: str
    country_code: str | None
    elevation: int | None
    importance: int
    location: LocationSchema
    place_type: str | CategorySchema | None = None
    sources: (
        list[OrganizationSourceIdSlugSchema]
        | list[OrganizationSourceIdDetailSchema]
        | None
    ) = None


class GeoPlaceSearchSchema(GeoPlaceBaseSchema):
    """Schema for search results with location coordinates."""

    score: float | None = None


class GeoPlaceDetailSchema(GeoPlaceSearchSchema):
    """Detailed schema for GeoPlace with all public fields."""

    parent: GeoPlaceBaseSchema | None = None


class GeoPlaceNearbySchema(GeoPlaceBaseSchema):
    """Schema for nearby places with distance information."""

    distance: float | None = None
