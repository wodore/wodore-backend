"""
Base classes and utilities for image providers.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Literal

from django.contrib.gis.geos import Point
from django.core.cache import cache

logger = logging.getLogger(__name__)


# Cache duration constants (in seconds)
CACHE_INDEFINITE = 365 * 24 * 60 * 60  # 1 year (~indefinite)
CACHE_LONGTERM = 30 * 24 * 60 * 60  # 30 days
CACHE_MEDIUM = 7 * 24 * 60 * 60  # 7 days
CACHE_SHORT = 24 * 60 * 60  # 24 hours
CACHE_VERY_SHORT = 6 * 60 * 60  # 6 hours


# Cache key prefix for all geoimages caching
CACHE_KEY_PREFIX = "geoimages"


def get_persistent_cache():
    """
    Get the persistent cache backend.

    Returns:
        Cache backend configured for long-term storage
    """
    from django.core.cache import caches

    return caches["persistent"]


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
    cache_backend: str = (
        "persistent"  # Cache backend to use ("default" or "persistent")
    )

    @abstractmethod
    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
        update_cache: bool = False,
    ) -> list[ImageResult]:
        """
        Fetch images for the given GeoPlaces.

        Args:
            geoplaces: List of GeoPlace objects within radius
            lat: Query latitude
            lon: Query longitude
            radius: Search radius in meters
            limit: Maximum number of results to return
            update_cache: If True, bypass cache and refresh cached data

        Returns:
            List of ImageResult objects (empty if no images or error)

        Note:
            Must never raise - catch and log errors internally.
        """
        raise NotImplementedError

    def get_cache(self):
        """
        Get the cache backend for this provider.

        Returns:
            Cache backend instance
        """
        from django.core.cache import caches

        return caches[self.cache_backend]

    def _get_cache_key(
        self,
        lat: float,
        lon: float,
        radius: float,
        precision: str = "precise",
    ) -> str:
        """
        Generate cache key for this provider.

        Format: geoimages:PROVIDER:images:lat:lon:radius:precision

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

        return f"{CACHE_KEY_PREFIX}:{self.source}:images:{lat_rounded}:{lon_rounded}:{radius}:{precision}"

    def _get_metadata_cache_key(self, identifier: str) -> str:
        """
        Generate cache key for detailed metadata.

        Format: geoimages:PROVIDER:metadata:identifier

        Use this for indefinitely cacheable metadata (e.g., detailed image info
        that requires a second API call and never changes).

        Args:
            identifier: Unique identifier (e.g., image ID, QID, filename)

        Returns:
            Cache key string
        """
        return f"{CACHE_KEY_PREFIX}:{self.source}:metadata:{identifier}"

    async def _get_cached_results(
        self,
        cache_key: str,
    ) -> list[ImageResult] | None:
        """Get cached results if available and fresh."""
        cache_instance = self.get_cache()
        data = cache_instance.get(cache_key)
        if data is not None:
            logger.debug(f"Cache HIT: {cache_key}")
            # Deserialize - stored as list of dicts
            return [ImageResult(**item) for item in data]
        logger.debug(f"Cache MISS: {cache_key}")
        return None

    def _set_cached_results(
        self,
        cache_key: str,
        results: list[ImageResult],
    ) -> None:
        """Cache results for this provider."""
        cache_instance = self.get_cache()
        # Serialize - convert to list of dicts using dataclasses.asdict
        data = [asdict(result) for result in results]
        cache_instance.set(cache_key, data, self.cache_ttl)

    def invalidate_cache(
        self, lat: float, lon: float, radius: float, precision: str = "precise"
    ) -> bool:
        """
        Invalidate a specific cache entry for this provider.

        Args:
            lat: Latitude
            lon: Longitude
            radius: Radius in meters
            precision: Precision level

        Returns:
            True if deleted, False otherwise
        """
        cache_key = self._get_cache_key(lat, lon, radius, precision)
        cache_instance = self.get_cache()
        deleted = cache_instance.delete(cache_key)
        if deleted:
            logger.info(f"Invalidated cache: {cache_key}")
        return deleted

    @classmethod
    def invalidate_all_provider_cache(cls, provider: str) -> int:
        """
        Invalidate all cache entries for a specific provider.

        This uses the cache versioning strategy - increments the version
        number so all old cache keys are automatically invalidated.

        Args:
            provider: Provider name (e.g., "camptocamp", "panoramax")

        Returns:
            New version number
        """
        cache_instance = get_persistent_cache()
        version_key = f"{CACHE_KEY_PREFIX}:{provider}:version"
        current_version = cache_instance.get(version_key, 1)
        new_version = current_version + 1
        cache_instance.set(version_key, new_version)
        logger.info(
            f"Invalidated all cache for provider '{provider}': v{current_version} -> v{new_version}"
        )
        return new_version


def _get_provider_info(provider_name: str) -> dict:
    """
    Get provider information from database.

    Args:
        provider_name: Name of the provider (e.g., "camptocamp", "panoramax")

    Returns:
        Dictionary with provider information
    """
    cache = get_persistent_cache()
    cache_key = f"{CACHE_KEY_PREFIX}:provider:{provider_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Fallback provider information for known providers
    provider_fallbacks = {
        "panoramax": {
            "name": "Panoramax",
            "slug": "panoramax",
            "url": "https://panoramax.xyz",
            "icon": None,
            "description": "Panoramax open geographic photo database",
        },
        "camptocamp": {
            "name": "Camptocamp",
            "slug": "camptocamp",
            "url": "https://www.camptocamp.org",
            "icon": None,
            "description": "Camptocamp outdoor activities database",
        },
        "wikidata": {
            "name": "Wikidata",
            "slug": "wikidata",
            "url": "https://www.wikidata.org",
            "icon": None,
            "description": "Wikidata free knowledge database",
        },
        "wikimedia_commons": {
            "name": "Wikimedia Commons",
            "slug": "wikimedia_commons",
            "url": "https://commons.wikimedia.org",
            "icon": None,
            "description": "Wikimedia Commons free media repository",
        },
        "mapillary": {
            "name": "Mapillary",
            "slug": "mapillary",
            "url": "https://www.mapillary.com",
            "icon": None,
            "description": "Mapillary street-level imagery",
        },
        "flickr": {
            "name": "Flickr",
            "slug": "flickr",
            "url": "https://www.flickr.com",
            "icon": None,
            "description": "Flickr photo sharing community",
        },
        "wodore": {
            "name": "Wodore",
            "slug": "wodore",
            "url": "https://wodore.org",
            "icon": None,
            "description": "Wodore outdoor platform",
        },
    }

    # Start with fallback or default
    provider_info = provider_fallbacks.get(
        provider_name,
        {
            "name": provider_name.capitalize(),
            "slug": provider_name,
            "url": None,
            "icon": None,
            "description": None,
        },
    )

    # Try to get provider from database (overrides fallback if exists)
    try:
        from server.apps.organizations.models import Organization
        from server.apps.images.transfomer import ImagorImage

        org = Organization.objects.filter(slug=provider_name).first()
        if org:
            # Convert logo URL to Imagor URL with size 128x128
            icon_url = None
            if org.logo and org.logo.url:
                imagor_img = ImagorImage(org.logo)
                icon_url = imagor_img.transform(
                    size="128x128", quality=85
                ).get_full_url()

            provider_info = {
                "name": org.name,
                "slug": org.slug,
                "url": org.url,
                "icon": icon_url,
                "description": org.description,
            }
            logger.debug(
                f"Found organization for {provider_name}: url={org.url}, logo={org.logo}"
            )
        else:
            logger.debug(f"No organization found for {provider_name}, using fallback")
    except Exception as e:
        logger.warning(f"Could not fetch provider info from database: {e}")

    # Cache indefinitely (provider info rarely changes)
    cache.set(cache_key, provider_info, CACHE_INDEFINITE)

    return provider_info


def _generate_license_slug(input_string: str) -> str:
    """
    Generate a normalized license slug from an input string.

    Examples:
    - "CC-BY-SA-4.0" -> "cc-by-sa-4.0"
    - "Creative Commons Attribution-ShareAlike 4.0" -> "cc-by-sa-4.0"
    - "MIT License" -> "mit"

    Args:
        input_string: Raw license string

    Returns:
        Normalized slug string
    """
    import re

    if not input_string:
        return "unknown"

    # Convert to lowercase
    slug = input_string.lower().strip()

    # Common mappings from various formats to standard slugs
    # Format: "pattern": "replacement_slug"
    common_licenses = {
        # Creative Commons
        r"cc[-\s]?by[-\s]?sa[-\s]?4\.0": "cc-by-sa-4.0",
        r"cc[-\s]?by[-\s]?4\.0": "cc-by-4.0",
        r"cc[-\s]?by[-\s]?nc[-\s]?sa[-\s]?4\.0": "cc-by-nc-sa-4.0",
        r"cc[-\s]?by[-\s]?nc[-\s]?nd[-\s]?4\.0": "cc-by-nc-nd-4.0",
        r"cc[-\s]?by[-\s]?nd[-\s]?4\.0": "cc-by-nd-4.0",
        r"cc[-\s]?by[-\s]?nc[-\s]?4\.0": "cc-by-nc-4.0",
        r"cc[-\s]?by[-\s]?sa[-\s]?3\.0": "cc-by-sa-3.0",
        r"cc[-\s]?by[-\s]?3\.0": "cc-by-3.0",
        r"cc[-\s]?by[-\s]?sa[-\s]?2\.0": "cc-by-sa-2.0",
        r"cc[-\s]?by[-\s]?2\.0": "cc-by-2.0",
        r"cc[-\s]?by[-\s]?sa[-\s]?1\.0": "cc-by-sa-1.0",
        r"cc[-\s]?by[-\s]?1\.0": "cc-by-1.0",
        r"cc0": "cc0",
        r"cc[-\s]?zero": "cc0",
        r"pdm": "pdm",
        r"public[-\s]?domain[-\s]?mark": "pdm",
        r"pd[-\s]?user": "pd-user",
        r"pd[-\s]?mark": "cc-pd-mark",
        # Other licenses
        r"mit[-\s]?license": "mit",
        r"gfdl": "gfdl",
        r"gnu[-\s]?free[-\s]?documentation[-\s]?license": "gfdl",
        r"apache[-\s]?2\.0": "apache-2.0",
        r"bsd[-\s]?2[-\s]?clause": "bsd-2-clause",
        r"bsd[-\s]?3[-\s]?clause": "bsd-3-clause",
        r"isc": "isc",
        r"copyright": "copyright",
        r"all[-\s]?rights[-\s]?reserved": "copyright",
        r"not[-\s]?public": "not-public",
        r"open[-\s]?data[-\s]?meteoswiss": "open-data-meteoswiss",
    }

    # Try to match against common licenses
    for pattern, replacement in common_licenses.items():
        if re.search(pattern, slug, re.IGNORECASE):
            return replacement

    # If no match, generate a simple slug
    # Remove special characters, keep alphanumerics, dots, hyphens
    slug = re.sub(r"[^\w\.\-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)  # Replace multiple hyphens with single
    slug = slug.strip("-")

    return slug if slug else "unknown"


def _get_license_info(slug: str | None) -> dict[str, str | None]:
    """
    Get license information from database, creating if necessary.

    Args:
        slug: License slug (e.g., 'cc-by-sa-4.0')

    Returns:
        Dictionary with slug, name, fullname, url, icon, icons (all 3 types), and description
    """
    if not slug:
        return {
            "slug": None,
            "name": None,
            "fullname": None,
            "url": None,
            "icon": None,
            "icons": None,
            "description": None,
        }

    cache = get_persistent_cache()
    cache_key = f"{CACHE_KEY_PREFIX}:license:{slug}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Try to get from database
    try:
        from server.apps.licenses.models import License

        license_obj = License.objects.filter(slug=slug).first()

        # Auto-create license if not found
        if not license_obj:
            logger.info(f"License '{slug}' not found in database, auto-creating...")

            # Generate reasonable defaults from slug
            generated_slug = _generate_license_slug(slug)
            generated_name = generated_slug.upper().replace("-", "-")
            generated_fullname = generated_name.replace("-", " ").title()

            # Generate URL for common licenses
            generated_url = None
            if generated_slug.startswith("cc-"):
                # Extract version and build URL
                parts = generated_slug.replace("cc-", "").split("-")
                if len(parts) >= 2:
                    license_type = "-".join(parts[:-1])  # e.g., "by-sa"
                    version = parts[-1]  # e.g., "4.0"
                    if version == "0":
                        generated_url = (
                            "https://creativecommons.org/publicdomain/zero/1.0/"
                        )
                    else:
                        generated_url = f"https://creativecommons.org/licenses/{license_type}/{version}/"

            # Create the license with review_status="new"
            license_obj = License.objects.create(
                slug=generated_slug,
                name=generated_name,
                fullname=generated_fullname,
                url=generated_url,
                category=None,  # No category assigned by default
                review_status="new",  # Mark as new for review
                is_active=True,
                order=License.get_next_order_number(),
            )
            logger.info(
                f"Created new license '{generated_slug}' with review_status='new'"
            )

        # Get symbol icons for this license from category (with full URLs)
        icons = {}
        if license_obj.category:
            try:
                # Category has symbol_detailed, symbol_simple, symbol_mono fields
                category = license_obj.category

                # Map Category symbol fields to icon style names
                # Use svg_file.url which returns full URL from FileField
                symbol_fields = {
                    "detailed": category.symbol_detailed,
                    "simple": category.symbol_simple,
                    "mono": category.symbol_mono,
                }

                for style, symbol in symbol_fields.items():
                    if symbol and symbol.svg_file:
                        icons[style] = symbol.svg_file.url
            except Exception as e:
                logger.debug(f"Could not fetch license symbols from category: {e}")

        license_info = {
            "slug": license_obj.slug,
            "name": license_obj.name,
            "fullname": license_obj.fullname,
            "url": license_obj.url,
            "category": license_obj.category_id,
            "icons": icons if icons else None,
            "description": license_obj.description,
        }

        # Cache indefinitely (license info rarely changes)
        cache.set(cache_key, license_info, CACHE_INDEFINITE)
        return license_info

    except Exception as e:
        logger.error(f"Error fetching/creating license '{slug}': {e}")

        # Return minimal info on error
        return {
            "slug": slug,
            "name": slug.upper(),
            "fullname": slug,
            "url": None,
            "category": None,
            "icons": None,
            "description": None,
        }


def _build_attribution(
    author: str | None,
    author_url: str | None,
    license_slug: str,
    license_name: str,
    license_url: str | None,
    provider_name: str,
    provider_url: str | None,
    source_url: str | None = None,
    provider_icon: str | None = None,
    license_icons: dict[str, str] | None = None,
) -> dict:
    """
    Build comprehensive attribution information for an image.

    Args:
        author: Author name
        author_url: Author profile URL
        license_slug: License identifier (e.g., 'cc-by-sa-4.0')
        license_name: Human-readable license name
        license_url: Link to license text
        provider_name: Provider/organization name
        provider_url: Provider website URL
        source_url: Source image URL (used when linking to provider)
        provider_icon: Provider icon URL
        license_icons: Dictionary of license icons by style (detailed, simple, mono)

    Returns:
        Dictionary with short, full, license_icons, license_short, license_full, and author fields
    """
    parts = []

    # Build author part
    author_html = ""
    author_display = ""
    if author:
        # Truncate long author names for short attribution (max 16 chars)
        author_display = author if len(author) <= 16 else author[:13] + "..."
        if author_url:
            author_html = (
                f'<a href="{author_url}" target="_blank" rel="nofollow">{author}</a>'
            )
            # Also create linked version with truncated text for short attribution
            author_display = f'<a href="{author_url}" target="_blank" rel="nofollow">{author_display}</a>'
        else:
            author_html = author
        parts.append(author_html)

    # Build license part
    license_short_html = ""
    license_full_html = ""
    if license_url:
        license_short_html = (
            f'<a href="{license_url}" target="_blank">{license_slug.upper()}</a>'
        )
        license_full_html = (
            f'<a href="{license_url}" target="_blank">{license_name}</a>'
        )
    else:
        license_short_html = license_slug.upper()
        license_full_html = license_name

    parts.append(license_short_html)

    # Build provider part - use source_url if available, otherwise provider_url
    provider_html = ""
    if provider_name:
        # Prefer source_url when org is used
        link_url = source_url or provider_url
        if link_url:
            provider_html = f'<a href="{link_url}" target="_blank" rel="nofollow">{provider_name}</a>'
        else:
            provider_html = provider_name
        parts.append(f"via {provider_html}")

    # Join for full attribution
    full_attribution = ", ".join(parts) if parts else "Unknown"

    # Build short attribution (license icon + author with provider icon)
    short_parts = []

    # License icon from symbols (prefer mono, then simple, then detailed)
    license_icon_url = None
    if license_icons:
        license_icon_url = (
            license_icons.get("mono")
            or license_icons.get("simple")
            or license_icons.get("detailed")
        )

    # License icon as img tag
    if license_icon_url:
        if license_url:
            short_parts.append(
                f'<a href="{license_url}" target="_blank"><img src="{license_icon_url}" alt="{license_slug}" style="height:15px; vertical-align: middle;"></a>'
            )
        else:
            short_parts.append(
                f'<img src="{license_icon_url}" alt="{license_slug}" style="height:15px;">'
            )
    elif license_url:
        # Fallback to text if no icon
        short_parts.append(license_short_html)

    # Author with provider icon as img
    if author_html:
        if provider_icon:
            short_parts.append(
                f'{author_display} <img src="{provider_icon}" alt="{provider_name}" style="height:15px; vertical-align: middle;">'
            )
        else:
            short_parts.append(author_display)
    elif provider_html:
        short_parts.append(provider_html)

    short_attribution = " · ".join(short_parts) if short_parts else full_attribution

    return {
        "short": short_attribution,
        "full": full_attribution,
        "license_icons": license_icons,
        "license_short": license_short_html,
        "license_full": license_full_html,
        "author": f"{author_html} on {provider_html}"
        if author_html and provider_html
        else (author_html or provider_html or "Unknown"),
    }


def _calculate_constrained_size(
    target_width: int,
    target_height: int,
    image_width: int | None,
    image_height: int | None,
) -> tuple[int, int]:
    """
    Calculate constrained size maintaining aspect ratio.

    If image dimensions are known, scales down the target size to fit within
    the original image dimensions while maintaining the target aspect ratio.

    Target aspect ratios:
    - Square: 1:1
    - Landscape: 3:2 (1.5:1)
    - Portrait: 2:3 (0.667:1)

    Args:
        target_width: Desired width
        target_height: Desired height
        image_width: Original image width (if known)
        image_height: Original image height (if known)

    Returns:
        Tuple of (width, height) constrained to image dimensions
    """
    # If we don't know the image dimensions, return target as-is
    if image_width is None or image_height is None:
        return target_width, target_height

    # Calculate target aspect ratio

    # Check if target fits within image
    if target_width <= image_width and target_height <= image_height:
        return target_width, target_height

    # Need to scale down - determine which dimension is the constraint
    width_ratio = image_width / target_width
    height_ratio = image_height / target_height

    # Use the more restrictive dimension (smaller ratio)
    scale_factor = min(width_ratio, height_ratio)

    # Calculate scaled dimensions
    scaled_width = int(target_width * scale_factor)
    scaled_height = int(target_height * scale_factor)

    return scaled_width, scaled_height


async def fetch_images_for_place(
    place_slug: str,
    place_type: Literal["geoplace", "hut"],
    radius: float,
    sources: list[str] | None,
    limit: int,
    update_cache: bool = False,
) -> tuple[list[ImageResult], dict[str, Any]]:
    """
    Fetch images for a specific place (GeoPlace or Hut).

    This helper function is used by both place/{slug} and hut/{slug} endpoints
    to avoid code duplication.

    Args:
        place_slug: Slug identifier for the place
        place_type: Either "geoplace" or "hut"
        radius: Search radius in meters for external providers
        sources: Optional list of providers to query
        limit: Max number of images to return
        update_cache: If True, bypass cache and refresh cached data

    Returns:
        Tuple of (list of ImageResult objects, place info dict)

    Raises:
        HttpError: If place is not found (404)
    """
    from asgiref.sync import sync_to_async
    from ninja.errors import HttpError

    # Fetch the place based on type (must be done in sync context)
    @sync_to_async
    def get_place():
        if place_type == "geoplace":
            from server.apps.geometries.models import GeoPlace

            place = GeoPlace.objects.filter(
                slug=place_slug, is_active=True, is_public=True
            ).first()

            if place is None:
                raise HttpError(404, f"GeoPlace '{place_slug}' not found")

            return {
                "place": place,
                "place_info": {
                    "id": place.id,
                    "slug": place.slug,
                    "name": place.name_i18n,
                    "location": {"lat": place.location.y, "lon": place.location.x},
                },
            }

        else:  # hut
            from server.apps.huts.models import Hut

            place = Hut.objects.filter(
                slug=place_slug, is_active=True, is_public=True
            ).first()

            if place is None:
                raise HttpError(404, f"Hut '{place_slug}' not found")

            return {
                "place": place,
                "place_info": {
                    "id": place.id,
                    "slug": place.slug,
                    "name": place.name_i18n,
                    "location": {"lat": place.location.y, "lon": place.location.x},
                },
            }

    place_data = await get_place()
    place = place_data["place"]
    place_info = place_data["place_info"]

    # Fetch images from all providers using the place
    results = await fetch_images_from_providers(
        geoplaces=[place] if place_type == "geoplace" else [],
        huts=[place] if place_type == "hut" else [],
        lat=place_info["location"]["lat"],
        lon=place_info["location"]["lon"],
        radius=radius,
        sources=sources,
        precision="precise",  # Always use high precision
        limit=limit,
        update_cache=update_cache,
    )

    return results, place_info


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

            # Helper function to generate constrained size
            def get_size(w: int, h: int) -> str:
                cw, ch = _calculate_constrained_size(w, h, result.width, result.height)
                return f"{cw}x{ch}"

            urls = {
                "original": {
                    "raw": result.url_large,
                    "proxy": imagor_img.transform().get_full_url(),
                },
                "square": {
                    "avatar": imagor_img.transform(
                        size=get_size(96, 96),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "avatar@2x": imagor_img.transform(
                        size=get_size(192, 192),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb": imagor_img.transform(
                        size=get_size(200, 200),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size=get_size(400, 400),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size=get_size(400, 400),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size=get_size(800, 800),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size=get_size(400, 400),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size=get_size(800, 800),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size=get_size(1000, 1000),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size=get_size(2000, 2000),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size=get_size(2000, 2000),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size=get_size(4000, 4000),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=True,
                    ).get_full_url(),
                },
                "landscape": {
                    "thumb": imagor_img.transform(
                        size=get_size(200, 133),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size=get_size(400, 266),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=focal_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size=get_size(400, 267),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size=get_size(800, 534),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size=get_size(400, 267),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size=get_size(800, 534),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size=get_size(1200, 800),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size=get_size(2400, 1600),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size=get_size(2000, 1333),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size=get_size(4000, 2666),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                },
                "portrait": {
                    "thumb": imagor_img.transform(
                        size=get_size(133, 200),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "thumb@2x": imagor_img.transform(
                        size=get_size(266, 400),
                        quality=quality,
                        focal=focal_point,
                        crop_start=focal_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview": imagor_img.transform(
                        size=get_size(300, 450),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "preview@2x": imagor_img.transform(
                        size=get_size(600, 900),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder": imagor_img.transform(
                        size=get_size(300, 450),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "placeholder@2x": imagor_img.transform(
                        size=get_size(600, 900),
                        quality=5,
                        blur=20,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                    ).get_full_url(),
                    "medium": imagor_img.transform(
                        size=get_size(900, 1350),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "medium@2x": imagor_img.transform(
                        size=get_size(1800, 2700),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "large": imagor_img.transform(
                        size=get_size(1500, 2250),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                    "large@2x": imagor_img.transform(
                        size=get_size(3000, 4500),
                        quality=quality,
                        focal=focal_point,
                        crop_start=crop_start,
                        crop_stop=crop_stop,
                        no_upscale=False,
                    ).get_full_url(),
                },
            }

            # Get provider and license information from database
            provider_info = _get_provider_info(result.provider)
            license_info = _get_license_info(result.license_slug)

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
                    "provider": provider_info,
                    "source_id": result.source_id,
                    "source_url": result.source_url,
                    "image_type": result.image_type,
                    "captured_at": result.captured_at.isoformat()
                    if result.captured_at
                    else None,
                    "distance_m": result.distance_m,
                    "license": {
                        "slug": result.license_slug,
                        "name": license_info.get("fullname")
                        or license_info.get("name")
                        or result.license_slug.upper(),
                        "url": license_info.get("url"),
                        "icon": license_info.get("icon"),
                    },
                    "attribution": _build_attribution(
                        author=result.author,
                        author_url=None,  # TODO: Extract from result if available
                        license_slug=result.license_slug,
                        license_name=license_info.get("fullname")
                        or result.license_slug,
                        license_url=license_info.get("url"),
                        provider_name=provider_info.get("name"),
                        provider_url=provider_info.get("url"),
                        source_url=result.source_url,
                        provider_icon=provider_info.get("icon"),
                        license_icons=license_info.get("icons"),
                    ),
                    "author": {
                        "name": result.author or "Unknown",
                        "url": None,  # TODO: Extract from result if available
                    },
                    "urls": urls,
                    "width": result.width,
                    "height": result.height,
                    "is_portrait": is_portrait,
                    "score": result.score,
                    "focal": focal_metadata,
                    "crop": crop_metadata,
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
    huts: list[Any] | None = None,
    update_cache: bool = False,
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
        huts: Optional list of Hut objects (if querying for huts)
        update_cache: If True, bypass cache and refresh cached data

    Returns:
        List of ImageResult objects from all providers
    """
    providers = provider_registry.get_enabled_providers(sources)

    if not providers:
        logger.warning("No enabled providers found")
        return []

    # Combine geoplaces and huts for providers
    all_places = list(geoplaces)
    if huts:
        all_places.extend(huts)

    # Log cache update mode
    if update_cache:
        logger.info(
            "🔄 UPDATE_CACHE mode: Bypassing cache and refreshing all providers"
        )

    # Run all providers in parallel
    tasks = [
        provider.fetch(all_places, lat, lon, radius, limit, update_cache=update_cache)
        for provider in providers
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
