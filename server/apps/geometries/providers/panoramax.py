"""
Provider for Panoramax images.
Uses Panoramax STAC API to find geolocated 360° images.
"""

import logging
from datetime import datetime, timezone
from typing import Any


from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema
from .scoring import (
    score_metadata_completeness,
    score_technical_quality,
    calculate_age_penalty,
)

logger = logging.getLogger(__name__)


class PanoramaxProvider(ImageProvider):
    """
    Provider for Panoramax images.

    Panoramax is an open-source platform for geolocated 360° images.
    Uses STAC API for querying images by location.
    """

    source = "panoramax"
    cache_ttl = 60  #  minute
    priority = 4  # After camptocamp, before wikidata

    def __init__(self, api_base: str = "https://api.panoramax.xyz"):
        """
        Initialize PanoramaxProvider.

        Args:
            api_base: Panoramax API base URL
        """
        self.api_base = api_base
        logger.debug(f"Initialized PanoramaxProvider with {api_base}")

    async def fetch(
        self,
        places: list[GeoPlaceSchema],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
        update_cache: bool = False,
    ) -> list[ImageResult]:
        """
        Fetch images from Panoramax using /api/search endpoint.

        Args:
            geoplaces: List of GeoPlace objects within radius (not used for bbox)
            lat: Query latitude (center point)
            lon: Query longitude (center point)
            radius: Search radius in meters
            limit: Maximum number of results to return
            update_cache: If True, bypass cache and refresh cached data

        Returns:
            List of ImageResult objects
        """
        try:
            # 1. Check cache first
            cache_key = self._get_cache_key(lat, lon, radius, "precise")
            if not update_cache:
                cached = await self._get_cached_results(cache_key)
                if cached is not None:
                    logger.debug(f"PanoramaxProvider: Cache HIT for {cache_key}")
                    return cached

            logger.debug("PanoramaxProvider: Cache MISS - fetching from API")

            # 2. Fetch from API
            import httpx
            from django.conf import settings

            # Calculate bbox from center point and radius
            bbox = self._calculate_bbox(lat, lon, radius)

            logger.debug(f"PanoramaxProvider: Searching in bbox {bbox}")

            headers = {
                "User-Agent": getattr(
                    settings, "BOT_AGENT", "WodoreBackend/1.0 (+https://wodore.ch)"
                )
            }

            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                # Single search request to /api/search
                url = f"{self.api_base}/api/search"
                params = {
                    "bbox": bbox,
                    "sort": "ts",
                    "limit": limit,  # Use requested limit
                }

                logger.debug(
                    f"Fetching Panoramax search from: {url} with params {params}"
                )

                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                features = data.get("features", [])

                logger.debug(f"PanoramaxProvider: Found {len(features)} items")

                # Parse all features
                results = []
                for feature in features:
                    try:
                        result = self._parse_stac_item(feature, lat, lon)
                        if result:
                            results.append(result)
                    except Exception as e:
                        logger.warning(f"Error parsing STAC item: {e}")
                        continue

                logger.debug(
                    f"PanoramaxProvider: Successfully parsed {len(results)} images"
                )

                # 3. Store in cache
                logger.debug(f"PanoramaxProvider: Caching {len(results)} results")
                await self._set_cached_results(cache_key, results)

                return results

        except Exception as e:
            logger.error(f"PanoramaxProvider error: {e}")
            return []

    def _calculate_bbox(self, lat: float, lon: float, radius: float) -> str:
        """
        Calculate bounding box from center point and radius.
        Returns bbox in WGS84 (min_lon,min_lat,max_lon,max_lat).

        Args:
            lat: Center latitude
            lon: Center longitude
            radius: Radius in meters

        Returns:
            BBOX string: "min_lon,min_lat,max_lon,max_lat"
        """
        import math

        # Convert radius from meters to degrees
        # 1 degree ≈ 111,000 meters (varies by latitude)
        lat_delta = radius / 111000.0
        lon_delta = radius / (111000.0 * math.cos(math.radians(lat)))

        min_lat = lat - lat_delta
        max_lat = lat + lat_delta
        min_lon = lon - lon_delta
        max_lon = lon + lon_delta

        return f"{min_lon},{min_lat},{max_lon},{max_lat}"

    def _parse_stac_item(
        self,
        feature: dict,
        query_lat: float,
        query_lon: float,
    ) -> ImageResult | None:
        """
        Parse a STAC item feature into ImageResult.

        Args:
            feature: STAC feature dictionary
            query_lat: Query latitude (for distance calculation)
            query_lon: Query longitude (for distance calculation)

        Returns:
            ImageResult or None
        """
        try:
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})

            if not geometry or geometry.get("type") != "Point":
                return None

            coordinates = geometry.get("coordinates", [])
            if len(coordinates) < 2:
                return None

            geom_lon, geom_lat = coordinates[0], coordinates[1]

            # Calculate distance
            from math import radians, cos, sin, asin, sqrt

            def haversine_distance(lat1, lon1, lat2, lon2):
                """Calculate distance between two points in meters."""
                R = 6371000  # Earth radius in meters

                lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
                dlat = lat2 - lat1
                dlon = lon2 - lon1

                a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
                c = 2 * asin(sqrt(a))

                return R * c

            distance_m = haversine_distance(query_lat, query_lon, geom_lat, geom_lon)

            # Extract image URLs from assets (STAC standard: assets at root level)
            assets = feature.get("assets", {})

            # Get different asset qualities for different use cases
            # Use hd for large/medium, sd for others (thumb, preview, avatar)
            hd_url = None
            sd_url = None

            for asset_type in [
                "hd",
                "sd",
                "thumb",
                "visual",
                "equirectangular",
                "preview",
            ]:
                if asset_type in assets:
                    asset = assets[asset_type]
                    if "href" in asset:
                        if asset_type == "hd":
                            hd_url = asset["href"]
                        elif asset_type == "sd":
                            sd_url = asset["href"]
                        elif not hd_url and not sd_url:
                            # Fallback if neither hd nor sd available yet
                            if asset_type == "thumb":
                                sd_url = asset["href"]
                            else:
                                if not hd_url:
                                    hd_url = asset["href"]
                                if not sd_url:
                                    sd_url = asset["href"]

            # Fallback to links if no assets found
            if not hd_url and not sd_url:
                links = feature.get("links", [])
                for link in links:
                    if link.get("rel") == "preview" or link.get("rel") == "visual":
                        hd_url = link.get("href")
                        sd_url = link.get("href")
                        break

            # Use sd as default if available, otherwise hd
            default_url = sd_url if sd_url else hd_url

            if not default_url:
                logger.debug("No image URL found in STAC item")
                return None

            # Get metadata
            datetime_str = properties.get("datetime")
            captured_at = None
            if datetime_str:
                # Parse ISO datetime
                from datetime import datetime

                try:
                    captured_at = datetime.fromisoformat(
                        datetime_str.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Determine image type (most Panoramax images are 360)
            image_type = "360"

            # License info (varies by collection)
            license_slug = "unknown"
            license_name = "Unknown"
            license_url = None

            # Try to get license from properties
            if "license" in properties:
                license_data = properties["license"]
                license_slug = self._normalize_license(license_data)
                license_name = license_data
                # Build license URL if it's just a slug
                if not license_data.startswith("http"):
                    license_url = self._get_license_url(license_data)
                else:
                    license_url = license_data

            # Build attribution
            # Try to get author from geovisio:producer field first
            author = properties.get("geovisio:producer")

            # Fallback to providers array
            if not author:
                providers = properties.get("providers")
                if providers and isinstance(providers, list) and len(providers) > 0:
                    author = providers[0].get("name", "Panoramax contributors")
                else:
                    author = "Panoramax contributors"

            attribution = f'{author}, <a href="{default_url}">Panoramax</a>'

            if license_url:
                attribution += f', <a href="{license_url}">{license_name}</a>'

            # Extract dimensions
            width = None
            height = None
            has_hd = "hd" in assets
            has_sd = "sd" in assets

            if has_hd and assets["hd"].get("width"):
                width = assets["hd"].get("width")
                height = assets["hd"].get("height")
            elif has_sd and assets["sd"].get("width"):
                width = assets["sd"].get("width")
                height = assets["sd"].get("height")

            from django.contrib.gis.geos import Point

            # Build source URL
            item_id = feature.get("id", "")
            collection_id = feature.get("collection", "")
            source_url = f"{self.api_base}/?pic={item_id}&seq={collection_id}"

            # Calculate score
            score = self._score_panoramax_image(feature, properties, assets)

            result = ImageResult(
                provider="panoramax",
                source_id=item_id,
                source_url=source_url,
                image_type=image_type,
                captured_at=captured_at,
                location=Point(geom_lon, geom_lat, srid=4326),
                distance_m=distance_m,
                license_slug=license_slug,
                attribution=attribution,
                author=author,
                author_url=None,
                url_large=hd_url or sd_url or default_url,
                url_medium=sd_url,
                width=width,
                height=height,
                place=None,  # Panoramax items are not GeoPlaces
                score=score,
            )

            return result

        except Exception as e:
            logger.warning(f"Error parsing STAC item: {e}")
            return None

    def _normalize_license(self, license_data: Any) -> str:
        """
        Normalize license to slug.

        Args:
            license_data: License data (could be string or dict)

        Returns:
            License slug (e.g., "cc-by-sa-4.0")
        """
        if isinstance(license_data, dict):
            license_url = license_data.get("link", "")
            if "creativecommons.org" in license_url:
                if "by-sa/4.0" in license_url:
                    return "cc-by-sa-4.0"
                elif "by/4.0" in license_url:
                    return "cc-by-4.0"
                elif "by-sa/3.0" in license_url:
                    return "cc-by-sa-3.0"
                elif "by/3.0" in license_url:
                    return "cc-by-3.0"
                elif "zero/1.0" in license_url:
                    return "cc0"
            return "unknown"

        # Handle simple string licenses like "CC-BY-SA-4.0"
        if isinstance(license_data, str):
            # Convert to lowercase and standardize format
            license_lower = license_data.lower()
            if "cc-by-sa-4.0" in license_lower or "by-sa/4.0" in license_lower:
                return "cc-by-sa-4.0"
            elif "cc-by-4.0" in license_lower or "by/4.0" in license_lower:
                return "cc-by-4.0"
            elif "cc-by-sa-3.0" in license_lower or "by-sa/3.0" in license_lower:
                return "cc-by-sa-3.0"
            elif "cc-by-3.0" in license_lower or "by/3.0" in license_lower:
                return "cc-by-3.0"
            elif "cc0" in license_lower or "zero/1.0" in license_lower:
                return "cc0"

        return str(license_data) if license_data else "unknown"

    def _get_license_url(self, license_slug: str) -> str | None:
        """
        Convert license slug to full URL.

        Args:
            license_slug: License slug (e.g., "CC-BY-SA-4.0")

        Returns:
            License URL or None
        """
        if not license_slug:
            return None

        license_lower = license_slug.lower()

        if "by-sa-4.0" in license_lower or "by-sa/4.0" in license_lower:
            return "https://creativecommons.org/licenses/by-sa/4.0/"
        elif "by-4.0" in license_lower or "by/4.0" in license_lower:
            return "https://creativecommons.org/licenses/by/4.0/"
        elif "by-sa-3.0" in license_lower or "by-sa/3.0" in license_lower:
            return "https://creativecommons.org/licenses/by-sa/3.0/"
        elif "by-3.0" in license_lower or "by/3.0" in license_lower:
            return "https://creativecommons.org/licenses/by/3.0/"
        elif "cc0" in license_lower:
            return "https://creativecommons.org/publicdomain/zero/1.0/"

        return None

    def _score_panoramax_image(
        self, feature: dict, properties: dict, assets: dict
    ) -> int:
        """
        Score Panoramax image (0-100).

        Higher score indicates better quality and relevance.
        Street view sequences (large collections) get lower scores.

        Args:
            feature: STAC feature dictionary
            properties: Feature properties
            assets: Feature assets

        Returns:
            Score from 0-100
        """
        score = 0

        # Source origin (0-50)
        # Panoramax is a curated 360° platform
        score += 30

        # Collection size penalty (0-20)
        # Individual panoramas or small collections score higher
        # Street view sequences (100+ images) are heavily penalized
        # Check if it's a street view sequence (usually longer collection IDs)
        # This is a heuristic - we'd need to fetch collection metadata for exact count
        # For now, we can't easily determine size without additional API calls
        # This could be enhanced in the future with collection metadata caching

        # Metadata completeness (0-25)
        has_description = bool(properties.get("datetime"))
        has_author = bool(properties.get("geovisio:producer"))
        has_license = bool(properties.get("license"))
        has_date = bool(properties.get("datetime"))

        score += score_metadata_completeness(
            has_description=has_description,
            has_author=has_author,
            has_license=has_license,
            has_date=has_date,
        )

        # Technical quality (0-30) - using enhanced scoring
        # Get image dimensions from assets if available
        width = None
        height = None

        for asset_name in ["hd", "sd", "thumbnail"]:
            if asset_name in assets:
                asset = assets[asset_name]
                # Try to get width/height from asset properties
                width = asset.get("width") or width
                height = asset.get("height") or height
                if width and height:
                    break

        # Get file size from hd asset if available
        file_size = None
        if "hd" in assets:
            file_size = assets["hd"].get("file:size")

        score += score_technical_quality(
            width=width,
            height=height,
            mime_type=None,  # Not scored anymore
            file_size=file_size,
        )

        # Individual panorama bonus (0-15)
        # If the image has a specific title/description, it's likely a standalone panorama
        # rather than part of an automated street view sequence
        if properties.get("title") or properties.get("description"):
            score += 10  # Likely individual/curated panorama
        else:
            score -= 5  # Likely automated street view (penalty)

        # Age penalty (0 to -40) - replaced recency bonus
        if properties.get("datetime"):
            try:
                captured_dt = datetime.fromisoformat(
                    properties["datetime"].replace("Z", "+00:00")
                )
                if captured_dt.tzinfo is None:
                    captured_dt = captured_dt.replace(tzinfo=timezone.utc)

                days_old = (datetime.now(timezone.utc) - captured_dt).days
                score += calculate_age_penalty(days_old)
            except Exception:
                pass  # If date parsing fails, no penalty

        return min(score, 100)
