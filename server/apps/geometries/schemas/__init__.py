"""
GeoPlace schemas for API responses and data input.

Output schemas (_output.py): Used for API responses
Input schemas (_input.py): Used for creating/updating GeoPlace models
Image schemas (_images.py): Used for image aggregation API
"""

# Output schemas (for API responses)
# Image schemas (for image aggregation API)
from ._images import (
    DEFAULT_THUMBHASHES,
    ImageCenterSchema,
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
    DedupOptions,
    DeletePolicyEnum,
    GeoPlaceAdminInput,
    GeoPlaceAmenityInput,
    GeoPlaceBaseInput,
    GeoPlaceNaturalInput,
    GeoPlaceTransportInput,
    OperationInput,
    PartyInput,
    PlaceTypeInput,
    ReviewStatus,
    SeasonalityInput,
    SourceInput,
    UpdatePolicyEnum,
)
from ._output import (
    AmenityDetailSchema,
    CategoryPlaceTypeSchema,
    CategorySchema,
    GeoPlaceBaseSchema,
    GeoPlaceDetailSchema,
    GeoPlaceNearbySchema,
    GeoPlaceSearchSchema,
    LinkSchema,
    PartyLinkSchema,
    PartySchema,
    SymbolSchema,
)

__all__ = [
    "DEFAULT_THUMBHASHES",
    "AmenityDetailSchema",
    "CategoryPlaceTypeSchema",
    "CategorySchema",
    "DedupOptions",
    "DeletePolicyEnum",
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
    "ImageCenterSchema",
    "ImageFeature",
    "ImageFeatureCollection",
    "ImageLicenseSchema",
    "ImageMetadataSchema",
    "ImagePlaceReferenceSchema",
    "ImagePropertiesSchema",
    "ImageProviderSchema",
    "ImageUrlsSchema",
    "PartyInput",
    "PartyLinkSchema",
    "PlaceTypeInput",
    "OperationInput",
    "SeasonalityInput",
    "PartySchema",
    "LinkSchema",
    "ReviewStatus",
    "SourceInput",
    "SymbolSchema",
    "UpdatePolicyEnum",
]
