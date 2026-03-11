"""
Pydantic schemas for image aggregation API.
Defines the unified image schema returned by all providers.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ImageLicenseSchema(BaseModel):
    """License information for an image."""

    slug: str = Field(..., description="License slug (e.g., 'cc-by-sa-4.0', 'cc0')")
    name: str = Field(..., description="Human-readable license name")
    url: str | None = Field(None, description="Link to license text")


class ImageUrlsSchema(BaseModel):
    """Image URLs for different sizes and orientations."""

    original: str = Field(..., description="Original unproxied source URL")
    placeholder: str | None = Field(
        None, description="Low-res placeholder for lazy loading"
    )
    portrait: dict[str, str] | None = Field(
        None, description="Portrait-oriented image URLs"
    )
    landscape: dict[str, str] | None = Field(
        None, description="Landscape-oriented image URLs"
    )
    preferred: str | None = Field(
        None, description="Preferred orientation URL based on image dimensions"
    )


class ImagePropertiesSchema(BaseModel):
    """
    Properties for an image GeoJSON feature.
    Follows the pattern from HutAvailabilityPropertiesSchema.
    """

    # Source identification
    source: str = Field(
        ..., description="Provider identifier (e.g., 'wodore', 'wikidata', 'flickr')"
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

    # Attribution
    license: ImageLicenseSchema = Field(..., description="Image license information")
    attribution: str = Field(..., description="Ready-to-render HTML attribution string")
    author: str | None = Field(None, description="Image author name")

    # URLs
    urls: dict[str, str] = Field(..., description="Image URLs for different sizes")

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

    # Source tracking
    source_found: list[str] | None = Field(
        None,
        description="Sources where this image was found (e.g., ['osm', 'wikidata'])",
    )
    source_organization: dict[str, Any] | None = Field(
        None, description="Organization information if available"
    )

    # Optional: Link back to GeoPlace (if image is associated with a place)
    place: dict[str, Any] | None = Field(
        None, description="Associated GeoPlace reference"
    )
