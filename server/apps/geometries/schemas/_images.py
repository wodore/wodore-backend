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
    url: str | None = Field(None, description="Link to the license text")
    icon: str | None = Field(None, description="URL to a license icon")


class ImageProviderSchema(BaseModel):
    """Provider that sourced the image."""

    slug: str = Field(
        ..., description="Provider slug (e.g., 'wikicommons', 'camptocamp', 'wodore')"
    )
    name: str = Field(..., description="Provider display name")
    url: str | None = Field(None, description="Provider website URL")
    icon: str | None = Field(None, description="Provider icon (128x128 via imagor)")
    description: str | None = Field(None, description="Short provider description")


class ImageAuthorSchema(BaseModel):
    """Photographer/author of the image."""

    name: str | None = Field(None, description="Author name")
    url: str | None = Field(None, description="Author profile URL")


class ImageAttributionSchema(BaseModel):
    """Ready-to-display attribution."""

    short: str = Field(..., description="Short HTML attribution (license icon + links)")
    full: str = Field(
        ..., description="Full attribution text (e.g., 'CC BY-SA 4.0, Author Name')"
    )
    license_icon: str | None = Field(None, description="URL to the license icon")
    license_short: str = Field(..., description="Short license name")
    license_full: str = Field(..., description="Full license name")
    author: str = Field(
        ..., description="Author with provider (e.g., 'Name on Wikimedia')"
    )


class ImageOriginalUrlsSchema(BaseModel):
    """Untransformed source URLs."""

    raw: str = Field(
        ...,
        description="Direct URL to the source image (for Wikimedia, a bounded thumb — never the true original)",
    )
    proxy: str = Field(
        ...,
        description="Full-size image served through imagor (JPEG — browsers cannot render TIFF)",
    )


class ImageVariantUrlsSchema(BaseModel):
    """URLs for one aspect group, sized xs through xl.

    | Key | ~Size (long edge) | Crop |
    |-----|-------------------|------|
    | xs  | ~200px            | focal area |
    | sm  | ~400px            | focal area |
    | md  | ~1200px           | curated crop |
    | lg  | ~2000px           | curated crop |
    | xl  | ~4000px           | curated crop |

    For retina, use the next size up: `sizes[min(i + (dpr > 1), 4)]`.
    Use `thumbhashes` for loading placeholders.
    """

    xs: str = Field(
        ..., description="Extra small (~200px) — cards, thumbnails. Focal-cropped."
    )
    sm: str = Field(
        ..., description="Small (~400px) — previews, 2x thumbnails. Focal-cropped."
    )
    md: str = Field(..., description="Medium (~1200px) — gallery, 2x previews")
    lg: str = Field(..., description="Large (~2000px) — hero images, 2x gallery")
    xl: str = Field(..., description="Extra large (~4000px) — fullscreen, 2x heroes")


class ImageUrlsSchema(BaseModel):
    """Image URLs grouped by aspect ratio.

    Pick the group via `is_portrait`; each group has xs–xl sizes.
    Square variants are always width == height.
    """

    original: ImageOriginalUrlsSchema = Field(
        ...,
        description="Untransformed source URLs (raw + imagor proxy)",
    )
    square: ImageVariantUrlsSchema = Field(
        ...,
        description="Square (1:1) variants — for cards and thumbnails",
    )
    landscape: ImageVariantUrlsSchema = Field(
        ...,
        description="Landscape (3:2) variants — use when `is_portrait` is false",
    )
    portrait: ImageVariantUrlsSchema = Field(
        ...,
        description="Portrait (2:3) variants — use when `is_portrait` is true",
    )


class ImagePlaceReferenceSchema(BaseModel):
    """The GeoPlace or Hut this image is pinned to."""

    id: int | None = Field(None, description="Place database ID")
    slug: str = Field(..., description="Place slug")
    name: str = Field(..., description="Place name")
    location: LocationSchema = Field(..., description="Place coordinates")


class ImageThumbhashesSchema(BaseModel):
    """ThumbHash placeholder per rendering context.

    Two crop styles × three aspect groups = six hashes.
    `thumb_*` = focal-cropped (matches xs/sm URLs);
    `preview_*` = curated crop (matches md+ URLs).
    Decode with https://evanw.github.io/thumbhash/ for instant blurred
    previews. Individual hashes are null when not yet assessed.
    """

    thumb_square: str | None = Field(None, description="Square (1:1) focal-cropped")
    thumb_landscape: str | None = Field(
        None, description="Landscape (3:2) focal-cropped"
    )
    thumb_portrait: str | None = Field(None, description="Portrait (2:3) focal-cropped")
    preview_square: str | None = Field(None, description="Square (1:1) curated crop")
    preview_landscape: str | None = Field(
        None, description="Landscape (3:2) curated crop"
    )
    preview_portrait: str | None = Field(
        None, description="Portrait (2:3) curated crop"
    )


class ImageDimensionsSchema(BaseModel):
    """Pixel dimensions of one variant."""

    width: int = Field(..., description="Width in pixels")
    height: int = Field(..., description="Height in pixels")


class ImagePropertiesSchema(BaseModel):
    """Properties for an image GeoJSON feature."""

    provider: ImageProviderSchema = Field(
        ..., description="Provider that sourced the image"
    )
    source_id: str = Field(
        ...,
        description="Unique ID in the source system (e.g., 'File:Example.jpg' for Wikimedia)",
    )
    source_url: str | None = Field(
        None, description="Deep link to the source page (attribution/provenance)"
    )
    image_type: Literal["flat", "360"] = Field(
        ..., description="'flat' (standard photo) or '360' (panorama)"
    )
    captured_at: datetime | None = Field(
        None, description="When the photo was taken (EXIF or provider metadata)"
    )
    distance_m: float = Field(
        ..., description="Distance from the query coordinate in meters"
    )
    attribution: ImageAttributionSchema = Field(
        ..., description="Ready-to-display attribution"
    )
    author: ImageAuthorSchema | None = Field(
        None, description="Image author/photographer"
    )
    license: ImageLicenseSchema = Field(..., description="License information")

    urls: ImageUrlsSchema = Field(
        ...,
        description="Image URLs for all sizes, grouped by aspect ratio (square/landscape/portrait)",
    )
    sizes: dict[str, ImageDimensionsSchema] = Field(
        ...,
        description=(
            "Pixel dimensions per size key (raw, xs, sm, md, lg, xl) "
            "for the image's own orientation. Square variants are always "
            "width == height; derive from sizes.raw constrained to a square."
        ),
    )
    is_portrait: bool | None = Field(
        None,
        description="True if the original is portrait (height > width). Pick urls.portrait when true, urls.landscape when false.",
    )
    place: ImagePlaceReferenceSchema | None = Field(
        None, description="The place this image is pinned to (if any)"
    )

    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Display order — higher appears first. Admin-adjustable curation position.",
    )

    thumbhashes: ImageThumbhashesSchema = Field(
        default_factory=ImageThumbhashesSchema,
        description=(
            "ThumbHash placeholder per rendering context (6 variants: "
            "thumb/preview × square/landscape/portrait). "
            "Individual hashes are null when not yet assessed."
        ),
    )


# GeoJSON types
ImageFeature = Feature[Point, ImagePropertiesSchema]


class ImageCenterSchema(BaseModel):
    """Query center point."""

    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class ImageMetadataSchema(BaseModel):
    """Query metadata."""

    total: int = Field(..., description="Number of images returned")
    sources_queried: list[str] = Field(
        ..., description="Provider sources that were queried"
    )
    query_radius_m: float = Field(..., description="Search radius in meters")
    center: ImageCenterSchema = Field(..., description="Query center point")
    geoplaces_found: int = Field(
        ..., description="GeoPlaces found within the search radius"
    )
    huts_found: int = Field(..., description="Huts found within the search radius")


class ImageFeatureCollection(FeatureCollection[ImageFeature]):
    """GeoJSON FeatureCollection of images."""


class ImageCollectionResponse(BaseModel):
    """Response for the image endpoints."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ImageFeature] = Field(
        ..., description="Image features, ordered by score (descending)"
    )
    metadata: ImageMetadataSchema = Field(..., description="Query metadata")
