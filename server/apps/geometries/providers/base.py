"""
Base classes and utilities for image providers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.gis.geos import Point
from django.core.cache import cache

logger = logging.getLogger(__name__)


@dataclass
class ImageArea:
    """
    Represents a rectangular area within an image for cropping or focal point.

    Coordinates are normalized to 0-1 range (relative to image dimensions).
    """

    x1: float  # Left coordinate (0-1)
    y1: float  # Top coordinate (0-1)
    x2: float  # Right coordinate (0-1)
    y2: float  # Bottom coordinate (0-1)

    def to_imagor_area(self) -> str:
        """
        Convert to Imagor area format (x1,y1:x2,y2).

        Returns normalized coordinates as a string for Imagor.
        """
        return f"{self.x1:.2f}x{self.y1:.2f}:{self.x2:.2f}x{self.y2:.2f}"

    def to_imagor_point(self) -> str:
        """
        Convert to Imagor focal point format (center_x,center_y).

        Calculates the center point of the area.
        """
        center_x = (self.x1 + self.x2) / 2
        center_y = (self.y1 + self.y2) / 2
        return f"{center_x:.2f},{center_y:.2f}"

    def to_imagor_crop(self) -> tuple[str, str]:
        x, y = self.to_imagor_area().split(":")
        return x, y


logger = logging.getLogger(__name__)


# Precision levels for cache key rounding
PRECISION_LEVELS = {
    "broad": 3,  # ~111m grid
    "normal": 4,  # ~11m grid
    "precise": 6,  # ~0.1m grid
}


@dataclass
class ImageResult:
    """
    Minimal internal image result returned by providers.
    Providers only return essential data - post-processing handles the rest.
    """

    # Core identification
    provider: str  # Provider name (e.g., "panoramax", "wikimedia_commons")
    source_id: str  # Unique ID within provider
    source_url: str | None  # Link to original source

    # Image metadata
    image_type: str  # "flat" or "360"
    captured_at: datetime | None
    location: Point  # PostGIS Point
    distance_m: float

    # Licensing
    license_slug: str  # e.g., "cc-by-sa-4.0"
    attribution: str  # HTML attribution string
    author: str | None

    # Image URLs (minimal - post-processing will generate others)
    url_large: str  # High-quality original URL
    url_medium: str | None = None  # Medium quality URL (if different from large)

    # Dimensions (optional - for orientation detection)
    width: int | None = None
    height: int | None = None

    # Image areas for cropping and focal point
    focal: ImageArea | None = None  # Focal point area (important region)
    crop: ImageArea | None = None  # Crop area (specific region to extract)

    # Additional provider-specific data
    extra: dict[str, Any] | None = None  # Any extra data provider wants to include

    # Place association (if image is linked to a specific GeoPlace)
    place: dict[str, Any] | None = None

    # Scoring (0-100)
    score: int = 0


class ImageProvider(ABC):
    """
    Abstract base class for image providers.
    All providers must implement this interface.
    """

    source: str  # Provider identifier
    cache_ttl: int  # Cache TTL in seconds
    priority: int  # Priority for deduplication (1=highest)

    @abstractmethod
    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """
        Fetch images for the given GeoPlaces.

        Args:
            geoplaces: List of GeoPlace objects within radius
            lat: Query latitude
            lon: Query longitude
            radius: Search radius in meters
            limit: Maximum number of results to return

        Returns:
            List of ImageResult objects (empty if no images or error)

        Note:
            Must never raise - catch and log errors internally.
        """
        raise NotImplementedError

    def _get_cache_key(
        self,
        lat: float,
        lon: float,
        radius: float,
        precision: str = "precise",
    ) -> str:
        """
        Generate cache key for this provider.

        Args:
            lat: Latitude
            lon: Longitude
            radius: Radius in meters
            precision: Precision level (broad, normal, precise)

        Returns:
            Cache key string
        """
        decimal_places = PRECISION_LEVELS.get(precision, 6)
        if decimal_places is not None:
            lat_rounded = round(lat, decimal_places)
            lon_rounded = round(lon, decimal_places)
        else:
            lat_rounded = lat
            lon_rounded = lon

        return f"images:{self.source}:{lat_rounded}:{lon_rounded}:{radius}"

    async def _get_cached_results(
        self,
        cache_key: str,
    ) -> list[ImageResult] | None:
        """Get cached results if available and fresh."""
        data = cache.get(cache_key)
        if data is not None:
            logger.debug(f"Cache HIT: {cache_key}")
            # Deserialize - stored as list of dicts
            return [ImageResult(**item) for item in data]
        logger.debug(f"Cache MISS: {cache_key}")
        return None


def _get_provider_info(provider_name: str) -> dict:
    """
    Get provider information from database.

    Args:
        provider_name: Name of the provider (e.g., "camptocamp", "panoramax")

    Returns:
        Dictionary with provider information
    """
    from django.core.cache import cache

    cache_key = f"provider_info:{provider_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    provider_info = {
        "name": provider_name.capitalize(),
        "slug": provider_name,
        "website": None,
        "icon": None,
    }

    # Try to get provider from database
    try:
        from server.apps.organizations.models import Organization

        org = Organization.objects.filter(slug=provider_name).first()
        if org:
            provider_info = {
                "name": org.name,
                "slug": org.slug,
                "website": org.website,
                "icon": org.logo.url if org.logo else None,
                "description": org.description,
            }
    except Exception as e:
        logger.debug(f"Could not fetch provider info from database: {e}")

    # Cache for 1 hour
    cache.set(cache_key, provider_info, 3600)

    return provider_info


def _get_license_name(slug: str | None) -> str | None:
    """Get human-readable license name from slug."""
    if not slug:
        return None
    license_names = {
        "cc-by-sa-4.0": "Creative Commons Attribution-ShareAlike 4.0",
        "cc-by-4.0": "Creative Commons Attribution 4.0",
        "cc-by-nc-sa-4.0": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0",
        "cc-by-nc-nd-4.0": "Creative Commons Attribution-NonCommercial-NoDerivs 4.0",
        "cc-by-nd-4.0": "Creative Commons Attribution-NoDerivs 4.0",
        "cc-by-nc-4.0": "Creative Commons Attribution-NonCommercial 4.0",
        "cc0": "Creative Commons CC0",
        "pdm": "Public Domain Mark",
        "copyright": "All Rights Reserved",
    }
    return license_names.get(slug, slug)


def _get_license_url(slug: str | None) -> str | None:
    """Get license URL from slug."""
    if not slug:
        return None
    license_urls = {
        "cc-by-sa-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
        "cc-by-4.0": "https://creativecommons.org/licenses/by/4.0/",
        "cc-by-nc-sa-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "cc-by-nc-nd-4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
        "cc-by-nd-4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
        "cc-by-nc-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
        "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
        "pdm": "https://creativecommons.org/publicdomain/mark/1.0/",
    }
    return license_urls.get(slug)


def post_process_images(
    results: list[ImageResult],
) -> list[dict]:
    """
    Post-process image results to generate final output format.

    This function:
    1. Generates all image URLs (portrait/landscape) from url_large
    2. Determines orientation from dimensions
    3. Creates final GeoJSON Feature format
    4. Adds license information from slug

    Args:
        results: List of ImageResult objects from providers

    Returns:
        List of GeoJSON Feature dictionaries
    """
    from server.apps.images.transfomer import ImagorImage

    final_results = []

    for result in results:
        try:
            # Determine orientation
            is_portrait = None

            if result.width and result.height:
                is_portrait = result.height > result.width

            # Use url_medium if available, otherwise url_large
            original_url = result.url_medium or result.url_large
            imagor_img = ImagorImage(original_url)

            # Determine focal point for transforms
            # Use focal area if available, otherwise default to smart detection
            focal_point = result.focal.to_imagor_area() if result.focal else "smart"

            # Determine crop parameters
            # If result.crop is defined, use it for all crops
            # Otherwise, use result.focal for avatar/thumb if focal_point is not smart
            crop_start = None
            crop_stop = None
            focal_start = None
            focal_stop = None
            if result.crop:
                # Parse crop string "x1,y1:x2,y2" into start and stop
                crop_start, crop_stop = result.crop.to_imagor_area()
            elif focal_point != "smart" and result.focal:
                # If no explicit crop but focal exists, use focal area for avatar/thumb only
                focal_start, focal_stop = result.focal.to_imagor_area()

            # Generate URLs with @2x variants
            quality = 85
            urls = {
                "original": {
                    "raw": result.url_large,
                    "proxy": imagor_img.transform().get_full_url(),
                },
                "square": {
                    "avatar": imagor_img.transform(
                        size="96x96",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "avatar@2x": imagor_img.transform(
                        size="192x192",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb": imagor_img.transform(
                        size="200x200",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size="400x400",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size="400x400",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size="800x800",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size="400x400",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size="800x800",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size="1000x1000",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size="2000x2000",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size="2000x2000",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size="4000x4000",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                },
                "landscape": {
                    "thumb": imagor_img.transform(
                        size="200x133",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size="400x266",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size="400x267",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size="800x534",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size="400x267",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size="800x534",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size="1200x800",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size="2400x1600",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size="2000x1333",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size="4000x2666",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                },
                "portrait": {
                    "thumb": imagor_img.transform(
                        size="133x200",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size="266x400",
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size="300x450",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size="600x900",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size="300x450",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size="600x900",
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size="900x1350",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size="1800x2700",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size="1500x2250",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size="3000x4500",
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                },
            }

            # Get provider information from database
            provider_info = _get_provider_info(result.provider)

            # Build focal and crop metadata
            focal_metadata = None
            crop_metadata = None

            if result.focal:
                focal_metadata = {
                    "x1": result.focal.x1,
                    "y1": result.focal.y1,
                    "x2": result.focal.x2,
                    "y2": result.focal.y2,
                }

            if result.crop:
                crop_metadata = {
                    "x1": result.crop.x1,
                    "y1": result.crop.y1,
                    "x2": result.crop.x2,
                    "y2": result.crop.y2,
                }

            # Build GeoJSON Feature
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [result.location.x, result.location.y],
                },
                "properties": {
                    "source": result.provider,
                    "source_id": result.source_id,
                    "source_url": result.source_url,
                    "image_type": result.image_type,
                    "captured_at": result.captured_at.isoformat()
                    if result.captured_at
                    else None,
                    "distance_m": result.distance_m,
                    "license": {
                        "slug": result.license_slug,
                        "name": _get_license_name(result.license_slug),
                        "url": _get_license_url(result.license_slug),
                    },
                    "attribution": result.attribution,
                    "author": result.author,
                    "urls": urls,
                    "width": result.width,
                    "height": result.height,
                    "is_portrait": is_portrait,
                    "score": result.score,
                    "focal": focal_metadata,
                    "crop": crop_metadata,
                    "provider": provider_info,
                    "place": result.place,
                },
            }

            # Add extra data if present
            if result.extra:
                feature["properties"]["extra"] = result.extra

            final_results.append(feature)

        except Exception as e:
            logger.warning(f"Error post-processing result {result.source_id}: {e}")
            continue

    return final_results

    def _set_cached_results(
        self,
        cache_key: str,
        results: list[ImageResult],
    ) -> None:
        """Cache results for this provider."""
        # Serialize - convert to list of dicts
        data = [result.__dict__ for result in results]
        cache.set(cache_key, data, self.cache_ttl)


class ProviderRegistry:
    """
    Registry for managing image providers.
    Singleton pattern for global access.
    """

    _instance = None
    _providers: dict[str, ImageProvider] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, provider: ImageProvider) -> None:
        """Register a new provider."""
        self._providers[provider.source] = provider
        logger.info(f"Registered image provider: {provider.source}")

    def get_provider(self, source: str) -> ImageProvider | None:
        """Get provider by source name."""
        return self._providers.get(source)

    def get_all_providers(self) -> list[ImageProvider]:
        """Get all registered providers."""
        return list(self._providers.values())

    def get_enabled_providers(
        self, sources: list[str] | None = None
    ) -> list[ImageProvider]:
        """
        Get enabled providers, optionally filtered by source names.

        Args:
            sources: Optional list of source names to include

        Returns:
            List of enabled providers in priority order
        """
        providers = self.get_all_providers()
        if sources:
            providers = [p for p in providers if p.source in sources]
        # Sort by priority (lower = higher priority)
        return sorted(providers, key=lambda p: p.priority)


# Global registry instance
provider_registry = ProviderRegistry()


async def fetch_images_from_providers(
    geoplaces: list[Any],
    lat: float,
    lon: float,
    radius: float,
    sources: list[str] | None = None,
    precision: str = "precise",
    limit: int = 100,
) -> list[ImageResult]:
    """
    Fetch images from all enabled providers in parallel.

    Args:
        geoplaces: List of GeoPlace objects within radius
        lat: Query latitude
        lon: Query longitude
        radius: Search radius in meters
        sources: Optional list of provider sources to include
        precision: Coordinate precision for caching
        limit: Maximum number of results to fetch per provider

    Returns:
        List of ImageResult objects from all providers
    """
    providers = provider_registry.get_enabled_providers(sources)

    if not providers:
        logger.warning("No enabled providers found")
        return []

    # Run all providers in parallel
    tasks = [
        provider.fetch(geoplaces, lat, lon, radius, limit) for provider in providers
    ]
    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten results and handle exceptions
    all_results = []
    for i, result_list in enumerate(results_lists):
        provider = providers[i]
        if isinstance(result_list, Exception):
            logger.error(f"Provider {provider.source} failed: {result_list}")
            continue
        if result_list:
            all_results.extend(result_list)
            logger.debug(
                f"Provider {provider.source} returned {len(result_list)} images"
            )

    logger.info(f"Total images fetched: {len(all_results)}")
    return all_results


def deduplicate_images(results: list[ImageResult]) -> list[ImageResult]:
    """
    Deduplicate images from multiple providers.

    Level 1: Exact match by (source, source_id) and Commons filename
    - Keeps image from highest-priority source

    Args:
        results: List of ImageResult objects from all providers

    Returns:
        Deduplicated list of ImageResult objects
    """
    if not results:
        return []

    # Provider priority for deduplication
    PRIORITY = {
        "wodore": 1,
        "camptocamp": 2,
        "wikidata": 3,
        "panoramax": 4,
        "mapillary": 5,
        "flickr": 6,
    }

    # Track seen images
    seen_source_id: dict[
        tuple[str, str], ImageResult
    ] = {}  # (provider, source_id) -> result
    seen_commons: dict[str, ImageResult] = {}  # normalized filename -> result

    deduped = []

    for result in results:
        # Check (provider, source_id) uniqueness
        key = (result.provider, result.source_id)
        if key in seen_source_id:
            existing = seen_source_id[key]
            if PRIORITY.get(result.provider, 99) < PRIORITY.get(existing.provider, 99):
                # Replace with higher priority provider
                seen_source_id[key] = result
                # Also update seen_commons if applicable
                commons_key = _normalize_commons_filename(result.source_url or "")
                if commons_key and commons_key in seen_commons:
                    seen_commons[commons_key] = result
            continue

        # Check Commons filename for Wikidata duplicates
        commons_key = _normalize_commons_filename(result.source_url or "")
        if commons_key:
            if commons_key in seen_commons:
                existing = seen_commons[commons_key]
                if PRIORITY.get(result.provider, 99) < PRIORITY.get(
                    existing.provider, 99
                ):
                    # Replace with higher priority provider
                    seen_commons[commons_key] = result
                    seen_source_id[key] = result
                continue
            seen_commons[commons_key] = result

        seen_source_id[key] = result
        deduped.append(result)

    logger.info(f"Deduplication: {len(results)} -> {len(deduped)} images")
    return deduped


def _normalize_commons_filename(url: str) -> str | None:
    """
    Normalize Wikimedia Commons URL to canonical filename.

    Args:
        url: Image URL

    Returns:
        Canonical filename or None if not a Commons URL
    """
    if not url:
        return None

    url_lower = url.lower()

    if (
        "commons.wikimedia.org" not in url_lower
        and "upload.wikimedia.org" not in url_lower
    ):
        return None

    # Extract filename from various Commons URL formats
    import re

    # Try to extract filename from upload.wikimedia.org URL
    upload_match = re.search(
        r"/[a-f0-9]/[a-f0-9]/([^/]+\.(?:jpg|jpeg|png|gif))", url, re.IGNORECASE
    )
    if upload_match:
        return upload_match.group(1)

    # Try to extract filename from wiki/File: URL
    wiki_match = re.search(r"/wiki/File:([^#]+)", url, re.IGNORECASE)
    if wiki_match:
        return wiki_match.group(1).replace("_", " ")

    return None
