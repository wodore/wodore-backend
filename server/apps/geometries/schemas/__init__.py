"""
GeoPlace schemas for API responses and data input.

Output schemas (_output.py): Used for API responses
Input schemas (_input.py): Used for creating/updating GeoPlace models
Image schemas (_images.py): Used for image aggregation API
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

# Image schemas (for image aggregation API)
from ._images import (
    ImageLicenseSchema,
    ImageUrlsSchema,
    ImagePropertiesSchema,
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
    # Image schemas
    "ImageLicenseSchema",
    "ImageUrlsSchema",
    "ImagePropertiesSchema",
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
