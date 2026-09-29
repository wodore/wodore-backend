"""
Pydantic schemas for image aggregation API.
Defines the unified image schema returned by all providers.
"""

from datetime import datetime
from typing import Literal

from geojson_pydantic import Feature, FeatureCollection, Point
from hut_services import LocationSchema
from pydantic import BaseModel, Field


class ImageLicenseSchema(BaseModel):
    """License information for an image."""

    slug: str = Field(..., description="License slug (e.g., 'cc-by-sa-4-0', 'cc0')")
    name: str = Field(..., description="Human-readable license name")
    url: str | None = Field(None, description="Link to license text")
    icon: str | None = Field(None, description="URL to license icon image")


class ImageProviderSchema(BaseModel):
    """Provider/organization information for an image."""

    slug: str = Field(
        ..., description="Provider slug (e.g., 'wikicommons', 'camptocamp', 'wodore')"
    )
    name: str = Field(..., description="Provider display name")
    url: str | None = Field(None, description="Provider website URL")
    icon: str | None = Field(
        None, description="Provider icon/logo URL (128x128 via imagor)"
    )
    description: str | None = Field(None, description="Provider description")


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
        description="Full attribution string (e.g., 'CC BY-SA 4.0, Author Name')",
    )
    license_icon: str | None = Field(None, description="URL to license icon image")
    license_short: str = Field(..., description="Short license name")
    license_full: str = Field(..., description="Full license name")
    author: str = Field(
        ..., description="Author name with provider (e.g., 'Name on Wikimedia')"
    )


class ImageOriginalUrlsSchema(BaseModel):
    """Original (untransformed) image URLs."""

    raw: str = Field(
        ..., description="Direct URL to the source image (never fed through imagor)"
    )
    proxy: str = Field(
        ..., description="Imagor-proxied full-size URL (JPEG even for TIFF sources)"
    )


class ImageVariantUrlsSchema(BaseModel):
    """Transformed variant URLs for one aspect group.

    Each variant has a base and a @2x (retina) URL. The `placeholder`
    is a low-quality blurred JPEG used as a loading fallback
    (deprecated in favour of ThumbHashes).
    """

    thumb: str = Field(
        ..., description="Small card/thumbnail URL (e.g., 200x133 landscape)"
    )
    thumb_2x: str = Field(..., description="Retina thumb URL (2x resolution)")
    preview: str = Field(
        ..., description="Medium preview URL (e.g., 400x267 landscape)"
    )
    preview_2x: str = Field(..., description="Retina preview URL")
    placeholder: str = Field(
        ...,
        description="Blurred low-quality placeholder URL (deprecated: use thumbhashes)",
    )
    placeholder_2x: str = Field(..., description="Retina placeholder URL (deprecated)")
    medium: str = Field(..., description="Large display URL (e.g., 1200x800 landscape)")
    medium_2x: str = Field(..., description="Retina medium URL")
    large: str = Field(..., description="Full detail URL (e.g., 2000x1333 landscape)")
    large_2x: str = Field(..., description="Retina large URL")


class ImageUrlsSchema(BaseModel):
    """Image URLs grouped by aspect ratio.

    Each group contains the same keys:
    `thumb`, `thumb@2x`, `preview`, `preview@2x`,
    `placeholder`, `placeholder@2x` (deprecated — use thumbhashes),
    `medium`, `medium@2x`, `large`, `large@2x`.
    The `square` group additionally has `avatar` and `avatar@2x`.
    """

    original: dict[str, str] = Field(
        ...,
        description="Original image URLs: `raw` (direct source) and `proxy` (imagor full-size)",
    )
    square: dict[str, str] | None = Field(
        None,
        description="Square (1:1) URLs — keys: avatar, avatar@2x, thumb, thumb@2x, preview, preview@2x, placeholder, placeholder@2x, medium, medium@2x, large, large@2x",
    )
    landscape: dict[str, str] | None = Field(
        None,
        description="Landscape (3:2) URLs — keys: thumb, thumb@2x, preview, preview@2x, placeholder, placeholder@2x, medium, medium@2x, large, large@2x",
    )
    portrait: dict[str, str] | None = Field(
        None,
        description="Portrait (2:3) URLs — keys: thumb, thumb@2x, preview, preview@2x, placeholder, placeholder@2x, medium, medium@2x, large, large@2x",
    )
    preferred: str | None = Field(
        None,
        description="URL of the preferred variant for this image's own orientation",
    )


class ImagePlaceReferenceSchema(BaseModel):
    """Brief reference to a GeoPlace or Hut associated with an image."""

    id: int | None = Field(None, description="Place database ID")
    slug: str = Field(..., description="Place slug identifier")
    name: str = Field(..., description="Place name")
    location: LocationSchema = Field(..., description="Place coordinates")


class ImageAreaSchema(BaseModel):
    """Normalized (0–1) rectangular area within an image."""

    x1: float = Field(..., ge=0, le=1, description="Left edge (0–1)")
    y1: float = Field(..., ge=0, le=1, description="Top edge (0–1)")
    x2: float = Field(..., ge=0, le=1, description="Right edge (0–1)")
    y2: float = Field(..., ge=0, le=1, description="Bottom edge (0–1)")


class ImageThumbhashesSchema(BaseModel):
    """ThumbHash placeholder per rendering context.

    Each hash is a ~30-char base64 string. Decode with a ThumbHash
    decoder (https://evanw.github.io/thumbhash/) for an instant blurred
    preview matching the exact crop of that variant. Null when the
    image has not been assessed yet.
    """

    thumb_square: str | None = Field(
        None,
        description="ThumbHash of the square (1:1) thumb variant",
    )
    thumb_landscape: str | None = Field(
        None,
        description="ThumbHash of the landscape (3:2) thumb variant",
    )
    thumb_portrait: str | None = Field(
        None,
        description="ThumbHash of the portrait (2:3) thumb variant",
    )
    preview: str | None = Field(
        None,
        description="ThumbHash of the preview variant in the image's own orientation",
    )


class ImageExtraSchema(BaseModel):
    """Assessment metadata (from the technical quality pipeline)."""

    quality_score: int | None = Field(
        None,
        ge=0,
        le=100,
        description="Technical quality score (0–100) from blur, exposure, contrast, resolution and saturation signals. Null when not yet assessed.",
    )
    duplicate_of: str | None = Field(
        None,
        description="Source identifier of the primary image this is a near-duplicate of (perceptual hash). Null when unique.",
    )


class ImagePropertiesSchema(BaseModel):
    """Properties for an image GeoJSON feature."""

    provider: ImageProviderSchema = Field(
        ..., description="Provider/organization information"
    )
    source_id: str = Field(
        ...,
        description="Unique ID in the source system (e.g., 'File:Example.jpg' for Wikimedia, 'waypoint_123' for camp2camp)",
    )
    source_url: str | None = Field(
        None, description="Deep link to the source page (attribution/provenance)"
    )

    image_type: Literal["flat", "360"] = Field(
        ..., description="Image type: 'flat' (standard photo) or '360' (panorama)"
    )
    captured_at: datetime | None = Field(
        None, description="When the photo was taken (EXIF or provider metadata)"
    )

    distance_m: float = Field(
        ..., description="Distance from the query coordinate in meters"
    )

    attribution: ImageAttributionSchema = Field(
        ..., description="Attribution information for display"
    )
    author: ImageAuthorSchema | None = Field(
        None, description="Image author/photographer details"
    )
    license: ImageLicenseSchema = Field(..., description="Image license information")

    urls: ImageUrlsSchema = Field(
        ...,
        description="Image URLs for all sizes and orientations, grouped by aspect ratio",
    )

    score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Curation score (0–100). For pinned images this is the admin-adjustable display order; higher appears first.",
    )

    width: int | None = Field(None, description="Original image width in pixels")
    height: int | None = Field(None, description="Original image height in pixels")
    is_portrait: bool | None = Field(
        None,
        description="True if height > width (portrait-oriented). Determines which urls group to use.",
    )

    focal: ImageAreaSchema | None = Field(
        None,
        description="Normalized focal area (x1, y1, x2, y2) — the region of interest used for smart cropping",
    )
    crop: ImageAreaSchema | None = Field(
        None,
        description="Normalized crop area (x1, y1, x2, y2) — explicit curated crop applied to preview/medium/large variants",
    )

    source_found: list[str] | None = Field(
        None,
        description="Provider sources where this image was found (e.g., ['osm', 'wikidata'])",
    )

    place: ImagePlaceReferenceSchema | None = Field(
        None, description="Associated GeoPlace or Hut reference (if pinned)"
    )

    thumbhashes: ImageThumbhashesSchema | None = Field(
        None,
        description=(
            "ThumbHash placeholder per rendering context. Decode the variant "
            "matching your display box for an instant blurred preview. "
            "Null when the image has not been assessed."
        ),
    )

    extra: ImageExtraSchema | None = Field(
        None,
        description="Assessment metadata (quality score, duplicate detection)",
    )


# GeoJSON types for nearby_images endpoint
ImageFeature = Feature[Point, ImagePropertiesSchema]


class ImageCenterSchema(BaseModel):
    """Query center point."""

    lat: float = Field(..., description="Latitude of the query center")
    lon: float = Field(..., description="Longitude of the query center")


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
    center: ImageCenterSchema = Field(..., description="Center point of the query")
    geoplaces_found: int = Field(
        ..., description="Number of GeoPlaces found within search radius"
    )
    huts_found: int = Field(
        ..., description="Number of Huts found within search radius"
    )


class ImageFeatureCollection(FeatureCollection[ImageFeature]):
    """GeoJSON FeatureCollection of images from multiple providers."""


class ImageCollectionResponse(BaseModel):
    """Complete response for nearby_images endpoint including metadata."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ImageFeature] = Field(
        ..., description="Image features ordered by curation score (descending)"
    )
    metadata: ImageMetadataSchema = Field(
        ..., description="Query metadata and source information"
    )
