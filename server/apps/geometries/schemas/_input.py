"""
Input schemas for creating/updating GeoPlace models.

These schemas are used for data import and creation.
They reuse existing schemas from hut_services and translations apps.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from hut_services import LocationSchema
from pydantic import BaseModel, Field

from server.apps.translations.schema import TranslationSchema

from ..models import OperatingStatus
from ..schemas import PhoneSchema


# Enums for type safety
class ReviewStatus(str, Enum):
    """Review status for GeoPlace."""

    NEW = "new"
    REVIEW = "review"
    WORK = "work"
    DONE = "done"


class DetailType(str, Enum):
    """Detail model types."""

    AMENITY = "amenity"
    TRANSPORT = "transport"
    ADMIN = "admin"
    NATURAL = "natural"
    NONE = "none"


class UpdatePolicyEnum(str, Enum):
    """How a source may update records."""

    ALWAYS = "always"
    MERGE = "merge"
    PROTECTED = "protected"
    AUTO_PROTECT = "auto_protect"


class DeletePolicyEnum(str, Enum):
    """What happens when a source no longer includes a record."""

    DEACTIVATE = "deactivate"
    KEEP = "keep"
    DELETE = "delete"
    AUTO_KEEP = "auto_keep"


# Helper schemas
class BrandInput(BaseModel):
    """Brand information."""

    slug: str  # Category slug for the brand
    name: str | None = None  # Optional brand name if not in category


class SourceInput(BaseModel):
    """Source information for GeoPlace association."""

    slug: str  # Organization slug (e.g., "osm", "geonames")
    source_id: str  # External ID (e.g., "node/123456", "2658434")
    import_date: datetime | None = None
    modified_date: datetime | None = None
    confidence: float = 1.0
    update_policy: UpdatePolicyEnum = UpdatePolicyEnum.AUTO_PROTECT
    delete_policy: DeletePolicyEnum = DeletePolicyEnum.AUTO_KEEP
    priority: int = 10
    extra: dict[str, Any] = Field(default_factory=dict)


class DedupOptions(BaseModel):
    """Deduplication options for finding existing places."""

    enabled: bool = True
    distance_same: int = 20  # Distance in meters for same category/brand
    distance_any: int = 4  # Distance in meters for any place (fallback)
    check_source_id: bool = True  # Check source ID first
    check_category: bool = True  # Match category parent when checking distance
    check_brand: bool = True  # Match brand when checking distance


class GeoPlaceBaseInput(BaseModel):
    """Base input schema for GeoPlace creation/update.

    This schema is used for all GeoPlace types and includes all common fields.
    All detail-specific fields are flattened into this schema for simplicity.
    """

    # Core identification
    name: str | TranslationSchema
    slug: str | None = None

    # Location
    location: LocationSchema
    elevation: int | None = None
    country_code: str

    # Classification
    place_type_identifiers: list[str]  # Category identifiers (e.g., ["shop.bakery"])
    detail_type: DetailType = DetailType.NONE

    # Optional fields
    description: str | TranslationSchema | None = None
    importance: int = 25
    review_status: ReviewStatus = ReviewStatus.NEW
    shape: Any | None = None  # Polygon geometry (GeoJSON or WKT)
    parent_id: int | None = None

    # Data fields
    osm_tags: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

    # Status
    is_active: bool = True
    is_public: bool = True

    # Note: is_modified and protected_fields are managed automatically by the model
    # and should NOT be set via schema

    # Amenity-specific fields (flattened)
    operating_status: OperatingStatus | None = None
    opening_months: dict[str, str] = Field(default_factory=dict)
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    phones: list[PhoneSchema] = Field(default_factory=list)
    brand: BrandInput | None = None

    # Admin-specific fields (flattened)
    admin_level: int | None = None
    population: int | None = None
    postal_code: str | None = None

    def get_name_dict(self) -> dict[str, str]:
        """Get name as a dictionary with language codes as keys.

        Returns:
            Dict with language codes as keys and name translations as values.
        """
        from django.conf import settings

        if isinstance(self.name, str):
            return {settings.LANGUAGE_CODE: self.name}
        # TranslationSchema has attributes for each language code
        return {
            lang_code: getattr(self.name, lang_code, "")
            for lang_code in settings.LANGUAGE_CODES
            if getattr(self.name, lang_code, "")
        }

    def get_description_dict(self) -> dict[str, str]:
        """Get description as a dictionary with language codes as keys."""
        from django.conf import settings

        if self.description is None:
            return {}
        if isinstance(self.description, str):
            return {settings.LANGUAGE_CODE: self.description}
        # TranslationSchema has attributes for each language code
        return {
            lang_code: getattr(self.description, lang_code, "")
            for lang_code in settings.LANGUAGE_CODES
            if getattr(self.description, lang_code, "")
        }


# Convenience aliases for specific types
class GeoPlaceAmenityInput(GeoPlaceBaseInput):
    """Input schema for amenity places.

    This is just an alias with detail_type pre-set to AMENITY.
    All amenity fields are in the base schema.
    """

    detail_type: DetailType = DetailType.AMENITY


class GeoPlaceTransportInput(GeoPlaceBaseInput):
    """Input schema for transport places.

    Note: TransportDetail model not yet implemented.
    """

    detail_type: DetailType = DetailType.TRANSPORT


class GeoPlaceAdminInput(GeoPlaceBaseInput):
    """Input schema for admin areas."""

    detail_type: DetailType = DetailType.ADMIN


class GeoPlaceNaturalInput(GeoPlaceBaseInput):
    """Input schema for natural features (peaks, passes, lakes, etc.)."""

    detail_type: DetailType = DetailType.NATURAL
