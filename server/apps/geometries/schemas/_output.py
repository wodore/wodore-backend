"""
Schemas for GeoPlace API endpoints.
"""

from typing import Any

import pydantic
from hut_services import LocationSchema
from pydantic import Field

from django.conf import settings
from django.http import HttpRequest

from server.apps.organizations.schema import (
    OrganizationSourceIdDetailSchema,
    OrganizationSourceIdSlugSchema,
)


class SymbolSchema(pydantic.BaseModel):
    """Schema for symbol URLs with different variants."""

    simple: str | None = None
    detailed: str | None = None
    mono: str | None = None

    @staticmethod
    def resolve_simple(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get simple symbol URL."""
        if not hasattr(obj, "symbol_primitive") or not obj.symbol_primitive:
            return None
        path = str(obj.symbol_primitive)
        if path.startswith("http"):
            return path
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if request and not media_url.startswith("http"):
            media_url = request.build_absolute_uri(media_url)
        return f"{media_url}{path}"

    @staticmethod
    def resolve_detailed(obj: Any, request: HttpRequest | None = None) -> str | None:
        """Get detailed symbol URL."""
        if not hasattr(obj, "symbol_color") or not obj.symbol_color:
            return None
        path = str(obj.symbol_color)
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


class CategorySchema(pydantic.BaseModel):
    """Schema for category information in GeoPlace responses."""

    model_config = pydantic.ConfigDict(from_attributes=True)

    slug: str
    name: str | None = Field(None, validation_alias="name_i18n")
    description: str | None = Field(None, validation_alias="description_i18n")
    symbol: SymbolSchema | None = None


class CategoryPlaceTypeSchema(pydantic.BaseModel):
    """Schema for category place type with symbols (used in GeoPlace)."""

    slug: str
    name: str
    description: str = ""
    symbol: dict[str, str] | None = None


class PartyLinkSchema(pydantic.BaseModel):
    """Schema for a party link (label + url)."""

    url: str
    label: str | None = None


class PartySchema(pydantic.BaseModel):
    """Schema for role-classified party associations (geoplace-parties)."""

    role: str  # role category identifier, e.g. "role.operator"
    slug: str
    name: str | None = Field(None, validation_alias="name_i18n")
    links: list[PartyLinkSchema] = Field(default_factory=list)
    symbol: dict[str, str] | None = None  # resolved color/mono URLs


class GeoPlaceBaseSchema(pydantic.BaseModel):
    """Base schema for GeoPlace with common fields."""

    slug: str
    name: str
    country_code: str | None
    elevation: int | None
    importance: int
    location: LocationSchema
    categories: list[str] | list[CategoryPlaceTypeSchema] | None = None
    sources: (
        list[OrganizationSourceIdSlugSchema]
        | list[OrganizationSourceIdDetailSchema]
        | None
    ) = None
    parties: list[PartySchema] | None = None


class GeoPlaceSearchSchema(GeoPlaceBaseSchema):
    """Schema for search results with location coordinates."""

    score: float | None = None


class GeoPlaceNearbySchema(GeoPlaceBaseSchema):
    """Schema for nearby places with distance information."""

    distance: float | None = None


# Amenity schemas


class PhoneSchema(pydantic.BaseModel):
    """Schema for phone number with optional label."""

    number: str
    label: str | None = None


class AmenityDetailSchema(pydantic.BaseModel):
    """Schema for amenity detailed information.

    Websites/links live at the place level (external links), overflow
    data on ``GeoPlace.extra`` — neither belongs on this block.
    """

    operating_status: str
    opening_months: dict[str, str] = Field(
        default_factory=dict,
        description="Monthly availability per month: {'jan': 'yes', 'feb': 'yes', ...}",
    )
    opening_hours: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured weekly hours per weekday + public holidays",
    )
    phones: list[PhoneSchema] = Field(default_factory=list)


class GeoPlaceDetailSchema(GeoPlaceBaseSchema):
    """Unified place detail (place-detail-endpoint).

    Required members: ``slug``, ``name``, ``detail_type`` (the type
    discriminator clients switch on), ``location``, ``importance``.
    Everything else is an optional member under the ``fields[places]``
    sparse-fieldset selection; detail blocks appear as sibling members
    named exactly after their ``detail_type`` value (``amenity`` now,
    ``admin``/``transport``/``natural`` later) and only for places of
    that type with a detail row.
    """

    description: str | None = None
    review_status: str | None = None
    detail_type: str
    amenity: AmenityDetailSchema | None = None
    # Required-but-nullable on the list schemas; optional members on
    # the detail endpoint — excludable via fields[places] selection.
    country_code: str | None = None
    elevation: int | None = None
