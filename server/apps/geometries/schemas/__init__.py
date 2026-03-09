"""
GeoPlace schemas for API responses and data input.

Output schemas (_output.py): Used for API responses
Input schemas (_input.py): Used for creating/updating GeoPlace models
"""

# Output schemas (for API responses)
from ._output import (
    AmenityDetailSchema,
    AmenitySchema,
    CategoryPlaceTypeSchema,
    CategorySchema,
    GeoPlaceBaseSchema,
    GeoPlaceDetailSchema,
    GeoPlaceNearbySchema,
    GeoPlaceSearchSchema,
    PhoneSchema,
    SymbolSchema,
    WebsiteSchema,
)

# Input schemas (for creating/updating models)
from ._input import (
    BrandInput,
    DedupOptions,
    DeletePolicyEnum,
    DetailType,
    GeoPlaceAdminInput,
    GeoPlaceAmenityInput,
    GeoPlaceBaseInput,
    GeoPlaceNaturalInput,
    GeoPlaceTransportInput,
    ReviewStatus,
    SourceInput,
    UpdatePolicyEnum,
)

__all__ = [
    # Output schemas
    "AmenityDetailSchema",
    "AmenitySchema",
    "CategoryPlaceTypeSchema",
    "CategorySchema",
    "GeoPlaceBaseSchema",
    "GeoPlaceDetailSchema",
    "GeoPlaceNearbySchema",
    "GeoPlaceSearchSchema",
    "PhoneSchema",
    "SymbolSchema",
    "WebsiteSchema",
    # Input schemas
    "BrandInput",
    "DedupOptions",
    "DeletePolicyEnum",
    "DetailType",
    "GeoPlaceAdminInput",
    "GeoPlaceAmenityInput",
    "GeoPlaceBaseInput",
    "GeoPlaceNaturalInput",
    "GeoPlaceTransportInput",
    "ReviewStatus",
    "SourceInput",
    "UpdatePolicyEnum",
]
