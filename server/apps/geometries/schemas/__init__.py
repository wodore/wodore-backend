"""
GeoPlace schemas for API responses and data input.

Output schemas (_output.py): Used for API responses
Input schemas (_input.py): Used for creating/updating GeoPlace models
Image schemas (_images.py): Used for image aggregation API
"""

# Output schemas (for API responses)
# Image schemas (for image aggregation API)
from ._images import (
    ImageCollectionResponse,
    ImageFeature,
    ImageFeatureCollection,
    ImageLicenseSchema,
    ImageMetadataSchema,
    ImagePlaceReferenceSchema,
    ImagePropertiesSchema,
    ImageProviderSchema,
    ImageUrlsSchema,
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

__all__ = [
    "# Image schemas",
    "# Input schemas",
    "# Output schemas",
    "AmenityDetailSchema",
    "AmenitySchema",
    "BrandInput",
    "CategoryPlaceTypeSchema",
    "CategorySchema",
    "DedupOptions",
    "DeletePolicyEnum",
    "DetailType",
    "GeoPlaceAdminInput",
    "GeoPlaceAmenityInput",
    "GeoPlaceBaseInput",
    "GeoPlaceBaseSchema",
    "GeoPlaceDetailSchema",
    "GeoPlaceNaturalInput",
    "GeoPlaceNearbySchema",
    "GeoPlaceSearchSchema",
    "GeoPlaceTransportInput",
    "ImageCollectionResponse",
    "ImageFeature",
    "ImageFeatureCollection",
    "ImageLicenseSchema",
    "ImageMetadataSchema",
    "ImagePlaceReferenceSchema",
    "ImagePropertiesSchema",
    "ImageProviderSchema",
    "ImageUrlsSchema",
    "PhoneSchema",
    "ReviewStatus",
    "SourceInput",
    "SymbolSchema",
    "UpdatePolicyEnum",
    "WebsiteSchema",
]
