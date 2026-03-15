"""
Pydantic schemas for image aggregation API.
Defines the unified image schema returned by all providers.
"""

from datetime import datetime

from geojson_pydantic import Feature, FeatureCollection, Point
from pydantic import BaseModel, Field

from hut_services import LocationSchema


class ImageLicenseSchema(BaseModel):
    """License information for an image."""

    slug: str = Field(..., description="License slug (e.g., 'cc-by-sa-4.0', 'cc0')")
    name: str = Field(..., description="Human-readable license name")
    url: str | None = Field(None, description="Link to license text")
    icon: str | None = Field(None, description="URL to license icon image")


class ImageProviderSchema(BaseModel):
    """Provider/organization information for an image."""

    slug: str = Field(..., description="Provider/organization slug")
    name: str = Field(..., description="Provider/organization name")
    url: str | None = Field(None, description="Provider/organization website URL")
    icon: str | None = Field(None, description="Provider/organization icon/logo URL")
    description: str | None = Field(
        None, description="Provider/organization description"
    )


class ImageAuthorSchema(BaseModel):
    """Author information for an image."""

    name: str | None = Field(None, description="Author name")
    url: str | None = Field(None, description="Author profile URL")


class ImageAttributionSchema(BaseModel):
    """Comprehensive attribution information for an image."""

    short: str = Field(
        ...,
        description="Short HTML attribution with license icon, license link, and provider link",
    )
    full: str = Field(
        ...,
        description="Full attribution string (e.g., 'CC BY-SA 4.0, Author Name on Wodore')",
    )
    license_icon: str | None = Field(None, description="URL to license icon image")
    license_short: str = Field(..., description="Short license name with link")
    license_full: str = Field(..., description="Full license name with link")
    author: str = Field(
        ..., description="Author name with provider link (e.g., 'Name on Wodore')"
    )


class ImageUrlsSchema(BaseModel):
    """Image URLs for different sizes and orientations."""

    original: dict[str, str] = Field(
        ..., description="Original image URLs (raw, proxy)"
    )
    square: dict[str, str] | None = Field(
        None,
        description="Square-cropped image URLs (avatar, thumb, preview, placeholder, medium, large with @2x variants)",
    )
    portrait: dict[str, str] | None = Field(
        None,
        description="Portrait-oriented image URLs (thumb, preview, placeholder, medium, large with @2x variants)",
    )
    landscape: dict[str, str] | None = Field(
        None,
        description="Landscape-oriented image URLs (thumb, preview, placeholder, medium, large with @2x variants)",
    )
    preferred: str | None = Field(
        None, description="Preferred orientation URL based on image dimensions"
    )


class ImagePlaceReferenceSchema(BaseModel):
    """Brief reference to a GeoPlace or Hut associated with an image."""

    id: int | None = Field(None, description="Place database ID")
    slug: str = Field(..., description="Place slug identifier")
    name: str = Field(..., description="Place name")
    location: LocationSchema = Field(..., description="Place coordinates")


class ImagePropertiesSchema(BaseModel):
    """
    Properties for an image GeoJSON feature.
    Follows the pattern from HutAvailabilityPropertiesSchema.
    """

    # Provider identification
    provider: ImageProviderSchema = Field(
        ..., description="Provider/organization information"
    )
    source_id: str = Field(..., description="Original ID in the source system")
    source_url: str | None = Field(None, description="Deep link back to the source")

    # Image metadata
    image_type: str = Field(..., description="Image type: 'flat' or '360'")
    captured_at: datetime | None = Field(None, description="When the photo was taken")

    # Distance from query point
    distance_m: float = Field(
        ..., description="Distance from query coordinate in meters"
    )

    # Attribution and licensing
    attribution: ImageAttributionSchema = Field(
        ..., description="Comprehensive attribution information"
    )
    author: ImageAuthorSchema | None = Field(None, description="Image author details")
    license: ImageLicenseSchema = Field(..., description="Image license information")

    # URLs
    urls: ImageUrlsSchema = Field(..., description="Image URLs for different sizes")

    # Quality score
    score: int = Field(
        default=0, ge=0, le=100, description="Metadata quality score (0-100)"
    )

    # Image dimensions
    width: int | None = Field(None, description="Image width in pixels")
    height: int | None = Field(None, description="Image height in pixels")
    is_portrait: bool | None = Field(
        None, description="True if image is portrait-oriented (height > width)"
    )

    # Focal and crop areas
    focal: dict[str, float] | None = Field(
        None,
        description="Focal point area coordinates (x1, y1, x2, y2) for smart cropping",
    )
    crop: dict[str, float] | None = Field(
        None,
        description="Crop area coordinates (x1, y1, x2, y2) for specific region extraction",
    )

    # Source tracking
    source_found: list[str] | None = Field(
        None,
        description="Sources where this image was found (e.g., ['osm', 'wikidata'])",
    )

    # Optional: Link back to GeoPlace (if image is associated with a place)
    place: ImagePlaceReferenceSchema | None = Field(
        None, description="Associated GeoPlace or Hut reference"
    )


# GeoJSON types for nearby_images endpoint
ImageFeature = Feature[Point, ImagePropertiesSchema]


class ImageMetadataSchema(BaseModel):
    """Metadata for the image collection response."""

    total: int = Field(
        ..., description="Total number of images returned in the collection"
    )
    sources_queried: list[str] = Field(
        ..., description="List of provider sources that were queried"
    )
    query_radius_m: float = Field(
        ..., description="Search radius used for the query in meters"
    )
    center: dict[str, float] = Field(
        ..., description="Center point of the query as {lat, lon}"
    )
    geoplaces_found: int = Field(
        ..., description="Number of GeoPlaces found within search radius"
    )
    huts_found: int = Field(
        ..., description="Number of Huts found within search radius"
    )


class ImageFeatureCollection(FeatureCollection[ImageFeature]):
    """GeoJSON FeatureCollection of images from multiple providers."""

    pass


class ImageCollectionResponse(BaseModel):
    """Complete response for nearby_images endpoint including metadata."""

    type: str = Field(default="FeatureCollection", description="GeoJSON type")
    features: list[ImageFeature] = Field(
        ..., description="List of image features as GeoJSON"
    )
    metadata: ImageMetadataSchema = Field(
        ..., description="Metadata about the image collection"
    )
