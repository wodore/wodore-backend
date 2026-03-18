"""
Provider for Camptocamp.org images.
Fetches images from Camptocamp API using bbox queries.
"""

# Test urls:
# Hollandiahütte SAC
#   https://api.camptocamp.org/waypoints/110216 (hut info)
#   https://api.camptocamp.org/images/452082 (direct image info)
#   https://www.camptocamp.org/images/452082/fr/hollandiahutte (image info page)
# Result api:
#   http://localhost:8000/v1/geo/images/hut/hollandia?lang=de&radius=50&limit=20&update_cache=1

import structlog
from datetime import datetime


from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema
from .scoring import (
    score_metadata_completeness,
    score_distance_relevance,
    calculate_age_penalty,
)

logger = structlog.get_logger()


class CamptocampProvider(ImageProvider):
    """
    Provider for Camptocamp.org images.

    License: CC-BY-SA or CC-BY-NC-ND
    Attribution required: author, source link, license.
    """

    source = "camptocamp"
    cache_ttl = 30 * 24 * 3600  # 31 days
    priority = 3  # Lower priority than wodore/wikidata

    def __init__(self, lang: str = "de"):
        """
        Initialize CamptocampProvider.

        Args:
            lang: Language for API responses (default: 'de')
        """
        self.lang = lang
        self.api_base = "https://api.camptocamp.org"
        self.media_base = "https://media.camptocamp.org/c2corg-active"
        logger.debug("Initialized CamptocampProvider", lang=lang)

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
        Fetch images from Camptocamp using bbox query.

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
                    logger.debug(
                        "Cache HIT", provider="camptocamp", cache_key=cache_key
                    )
                    return cached

            logger.debug("Cache MISS - fetching from API", provider="camptocamp")

            # 2. Fetch from API
            import httpx
            from django.conf import settings

            # Calculate bbox from center point and radius
            bbox = self._calculate_bbox(lat, lon, radius / 1000)  # Convert to km

            logger.debug("Fetching waypoints in bbox", provider="camptocamp", bbox=bbox)

            headers = {
                "User-Agent": getattr(
                    settings, "BOT_AGENT", "WodoreBackend/1.0 (+https://wodore.ch)"
                )
            }
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                # Step 1: Get all waypoints in bbox
                waypoints = await self._fetch_waypoints(client, bbox)

                if not waypoints:
                    logger.warning(
                        "No waypoints found in bbox", provider="camptocamp", bbox=bbox
                    )
                    await self._set_cached_results(cache_key, [])
                    return []

                logger.debug(
                    "Found waypoints", provider="camptocamp", count=len(waypoints)
                )

                # Step 2: Get details for each waypoint and extract images
                results = []
                max_waypoints = min(
                    len(waypoints), max(1, limit // 5)
                )  # Assume ~5 images per waypoint
                for waypoint in waypoints[
                    :max_waypoints
                ]:  # Limit waypoints based on desired result count
                    try:
                        waypoint_id = waypoint.get("document_id")
                        logger.debug(
                            "Fetching waypoint",
                            provider="camptocamp",
                            waypoint_id=waypoint_id,
                        )
                        images = await self._fetch_waypoint_images(
                            client, waypoint_id, lat, lon, radius, limit
                        )
                        logger.debug(
                            "Found images for waypoint",
                            provider="camptocamp",
                            waypoint_id=waypoint_id,
                            count=len(images),
                        )
                        results.extend(images)
                    except Exception as e:
                        logger.warning(
                            "Error processing waypoint",
                            provider="camptocamp",
                            waypoint_id=waypoint.get("document_id"),
                            error=str(e),
                        )
                        continue

                logger.debug(
                    "Total images found", provider="camptocamp", count=len(results)
                )

                # 3. Store in cache
                logger.debug(
                    "Caching results", provider="camptocamp", count=len(results)
                )
                await self._set_cached_results(cache_key, results)

                return results

        except Exception as e:
            logger.error("Provider error", provider="camptocamp", error=str(e))
            return []

    def _calculate_bbox(self, lat: float, lon: float, radius_km: float) -> str:
        """
        Calculate bounding box from center point and radius.
        Uses Web Mercator (EPSG:3857) which Camptocamp API expects.

        Args:
            lat: Center latitude
            lon: Center longitude
            radius_km: Radius in kilometers

        Returns:
            BBOX string: "min_x,min_y,max_x,max_y" (Web Mercator coordinates)
        """
        import math

        # Convert to Web Mercator (EPSG:3857)
        def to_web_mercator(lat, lon):
            """Convert WGS84 to Web Mercator."""
            x = 6378137.0 * lon * math.pi / 180.0
            y = 6378137.0 * math.log(math.tan((90.0 + lat) * math.pi / 360.0))
            return x, y

        # Calculate lat/lon bounds
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

        min_lat = lat - lat_delta
        max_lat = lat + lat_delta
        min_lon = lon - lon_delta
        max_lon = lon + lon_delta

        # Convert to Web Mercator
        min_x, min_y = to_web_mercator(min_lat, min_lon)
        max_x, max_y = to_web_mercator(max_lat, max_lon)

        return f"{int(min_x)},{int(min_y)},{int(max_x)},{int(max_y)}"

    async def _fetch_waypoints(self, client, bbox: str) -> list[dict]:
        """
        Fetch all waypoints in bbox.

        Args:
            client: HTTP client
            bbox: Bounding box string

        Returns:
            List of waypoint documents
        """
        url = f"{self.api_base}/waypoints"
        params = {"bbox": bbox, "limit": 100}

        response = await client.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        return data.get("documents", [])

    async def _fetch_waypoint_images(
        self,
        client,
        waypoint_id: int,
        query_lat: float,
        query_lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """
        Fetch images for a single waypoint.

        Args:
            client: HTTP client
            waypoint_id: Waypoint ID
            query_lat: Query latitude (for distance calculation)
            query_lon: Query longitude (for distance calculation)
            limit: Maximum number of images to return

        Returns:
            List of ImageResult objects
        """
        url = f"{self.api_base}/waypoints/{waypoint_id}"
        params = {"cook": self.lang}

        response = await client.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        # Get waypoint geometry from nested geometry.geom field
        geom_data = data.get("geometry", {})
        geom_json = geom_data.get("geom")

        if geom_json:
            try:
                import json

                geom_obj = json.loads(geom_json)
                coordinates = geom_obj.get("coordinates", [])
                if len(coordinates) >= 2:
                    # Web Mercator coordinates
                    mercator_x, mercator_y = coordinates[0], coordinates[1]

                    # Convert Web Mercator to WGS84
                    import math

                    lon = (mercator_x / 6378137.0) * 180.0 / math.pi
                    lat = (
                        (
                            math.pi / 2.0
                            - 2.0 * math.atan(math.exp(-mercator_y / 6378137.0))
                        )
                        * 180.0
                        / math.pi
                    )

                    geom_lon = lon
                    geom_lat = lat
                else:
                    logger.debug(
                        "Waypoint geometry has invalid coordinates",
                        provider="camptocamp",
                        waypoint_id=waypoint_id,
                    )
                    return []
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.debug(
                    "Failed to parse waypoint geometry",
                    provider="camptocamp",
                    waypoint_id=waypoint_id,
                    error=str(e),
                )
                return []
        else:
            # Fallback to main coordinates if no geometry
            geom_lat = data.get("lat")
            geom_lon = data.get("lon")

            if not geom_lat or not geom_lon:
                logger.debug(
                    "Waypoint has no coordinates",
                    provider="camptocamp",
                    waypoint_id=waypoint_id,
                )
                return []

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

        # Extract images from associations.images array
        associations = data.get("associations", {})
        images = associations.get("images", [])
        results = []

        logger.debug(
            "Waypoint has images in associations",
            provider="camptocamp",
            waypoint_id=waypoint_id,
            count=len(images),
        )

        max_images = min(len(images), limit)  # Respect overall limit
        for img in images[:max_images]:  # Limit to requested limit
            image_id = img.get("document_id")
            if not image_id:
                continue

            try:
                # Fetch detailed image information
                image_details = await self._fetch_image_details(client, image_id)
                if not image_details:
                    continue

                # Parse and create result
                result = await self._parse_camptocamp_image(
                    image_details, waypoint_id, geom_lat, geom_lon, distance_m, radius
                )
                if result:
                    results.append(result)

            except Exception as e:
                logger.warning(
                    "Error processing image",
                    provider="camptocamp",
                    image_id=image_id,
                    error=str(e),
                )
                continue

        return results

    async def _fetch_image_details(self, client, image_id: int) -> dict | None:
        """
        Fetch detailed information for a single image.

        Args:
            client: HTTP client
            image_id: Image ID

        Returns:
            Image details dict or None
        """
        url = f"{self.api_base}/images/{image_id}"
        params = {"cook": self.lang}

        response = await client.get(url, params=params)
        response.raise_for_status()

        return response.json()

    async def _parse_camptocamp_image(
        self,
        image_details: dict,
        waypoint_id: int,
        geom_lat: float,
        geom_lon: float,
        distance_m: float,
        radius: float,
    ) -> ImageResult | None:
        """
        Parse Camptocamp image details into ImageResult.

        Args:
            image_details: Image details from API
            waypoint_id: Associated waypoint ID
            geom_lat: Image latitude
            geom_lon: Image longitude
            distance_m: Distance from query point

        Returns:
            ImageResult or None
        """
        try:
            filename = image_details.get("filename")
            if not filename:
                return None

            # Use the URL with file extension from API response (urls.original.raw)
            # This ensures dimension fetching works correctly
            urls = image_details.get("urls", {})
            original_url = urls.get("original", {}).get("raw")

            # Fallback to manually constructed URL if urls.original.raw not available
            if not original_url:
                original_url = f"{self.media_base}/{filename}"

            # Extract metadata
            locales = image_details.get("locales", [])
            title = ""
            description = ""
            if locales:
                locale = locales[0]
                title = locale.get("title", "")
                description = locale.get("description", "")

            # Author information - prioritize 'author' field over 'creator'
            author = image_details.get("author")
            if not author:
                creator = image_details.get("creator")
                # Creator is a dict with 'name' and 'user_id', extract just the name
                if isinstance(creator, dict):
                    author = creator.get("name", "camptocamp.org")
                else:
                    author = creator if creator else "camptocamp.org"

            # Parse date_time if available
            captured_at = None
            date_time_str = image_details.get("date_time")
            if date_time_str and date_time_str != "1970-01-01T00:00:00+00:00":
                try:
                    # Parse ISO 8601 format
                    captured_at = datetime.fromisoformat(
                        date_time_str.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            # Image type for license determination
            image_type = image_details.get("image_type")  # collaborative, personal

            # Quality rating
            quality = image_details.get("quality", "medium")  # fine, medium, low

            # Determine license based on image type
            if image_type == "personal":
                license_slug = "cc-by-nc-nd-3.0"
                license_name = "CC BY-NC-ND 3.0"
                license_url = "https://creativecommons.org/licenses/by-nc-nd/3.0/"
            else:  # collaborative
                license_slug = "cc-by-sa-3.0"
                license_name = "CC BY-SA 3.0"
                license_url = "https://creativecommons.org/licenses/by-sa/3.0/"

            # Build source URL to image page
            # Format: https://www.camptocamp.org/images/{image_id}
            source_url = (
                f"https://www.camptocamp.org/images/{image_details.get('document_id')}"
            )

            # Build attribution
            if author and author != "camptocamp.org":
                attribution = f'{author} on <a href="{source_url}">camptocamp.org</a>, <a href="{license_url}">{license_name}</a>'
            else:
                attribution = f'<a href="{source_url}">camptocamp.org</a> (collaborative), <a href="{license_url}">{license_name}</a>'

            # Calculate score
            score = self._score_camptocamp_image(
                image_details,
                quality,
                distance_m,
                radius,
                has_title=bool(title),
                has_description=bool(description),
                captured_at=captured_at,
            )

            # Extract dimensions (not available in Camptocamp API)
            width = None
            height = None

            from django.contrib.gis.geos import Point

            # Build raw author string for deduplication
            # Concatenate all source info without formatting
            author_raw_parts = []
            if author:
                author_raw_parts.append(str(author))
            if image_details.get("creator"):
                creator = image_details.get("creator")
                if isinstance(creator, dict):
                    author_raw_parts.append(str(creator.get("name", "")))
                    author_raw_parts.append(str(creator.get("user_id", "")))
                else:
                    author_raw_parts.append(str(creator))
            author_raw_parts.append(source_url)  # Add source URL
            author_raw = " ".join(filter(None, author_raw_parts))

            return ImageResult(
                provider="camptocamp",
                source_id=f"waypoint_{waypoint_id}_{filename}",
                source_url=source_url,
                image_type="flat",
                captured_at=captured_at,
                location=Point(geom_lon, geom_lat, srid=4326),
                distance_m=distance_m,
                license_slug=license_slug,
                attribution=attribution,
                author=author,
                author_url=None,
                author_raw=author_raw,  # Raw concatenated author info for deduplication
                url_large=original_url,
                url_medium=None,  # Camptocamp doesn't provide medium URLs
                width=width,
                height=height,
                place=None,
                extra=None,
                score=score,
            )

        except Exception as e:
            logger.warning("Error parsing image", provider="camptocamp", error=str(e))
            return None

    def _score_camptocamp_image(
        self,
        image_details: dict,
        quality: str,
        distance_m: float,
        radius: float,
        has_title: bool = False,
        has_description: bool = False,
        captured_at: datetime | None = None,
    ) -> int:
        """
        Score Camptocamp image (0-100).

        Args:
            image_details: Image details from API
            quality: Quality rating (fine, medium, low)
            distance_m: Distance from query point in meters
            radius: Search radius in meters
            has_title: Image has title
            has_description: Image has description
            captured_at: Image capture date (if available)

        Returns:
            Score from 0-100
        """
        score = 0

        # Source origin (0-50)
        # Camptocamp is a curated outdoor community - stays at 40
        score += 40

        # Quality rating (0-20)
        quality_scores = {
            "fine": 20,
            "medium": 12,
            "low": 5,
        }
        score += quality_scores.get(quality, 10)

        # Distance relevance (0-20)
        # Images from closer waypoints get higher scores
        score += score_distance_relevance(distance_m, radius)

        # Metadata completeness (0-25)
        has_author = bool(image_details.get("author") or image_details.get("creator"))
        has_date = captured_at is not None
        has_license = True  # Always has license

        score += score_metadata_completeness(
            has_description=has_description,
            has_author=has_author,
            has_license=has_license,
            has_date=has_date,
        )

        # Age penalty (-50 to +5) - using global function
        from datetime import timezone

        if captured_at:
            days_old = (datetime.now(timezone.utc) - captured_at).days
            score += calculate_age_penalty(days_old)
        else:
            # No date available - use global penalty
            score += calculate_age_penalty(None)

        # Image type bonus (0-5)
        image_type = image_details.get("image_type")
        if image_type == "collaborative":
            score += 5  # Community-vetted content

        return max(0, min(score, 100))


if __name__ == "__main__":
    """
    Test the Camptocamp provider directly.
    Usage: python -m server.apps.geometries.providers.camptocamp
    """
    import asyncio
    import os
    import sys

    # Setup Django
    sys.path.insert(0, ".")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

    import django

    django.setup()

    async def test_camptocamp():
        """Test the Camptocamp provider."""
        from server.apps.geometries.providers.camptocamp import CamptocampProvider

        # Test coordinates
        lat = 46.55553
        lon = 8.15223
        radius = 100

        print("Testing CamptocampProvider...")
        print(f"Coordinates: {lat}, {lon}")
        print(f"Radius: {radius}m")
        print()

        # Create provider
        provider = CamptocampProvider(lang="de")

        # Fetch images
        print("Fetching images...")
        results = await provider.fetch([], lat, lon, radius)

        print(f"\n✓ Found {len(results)} images")

        if results:
            print("\nFirst 3 results:")
            for i, result in enumerate(results[:3], 1):
                print(f"\n{i}. {result.source_id}")
                print(f"   Distance: {result.distance_m:.0f}m")
                print(f"   License: {result.license_name}")
                print(f"   Author: {result.author}")
                print(f"   Attribution: {result.attribution}")
                print(f"   URL: {result.urls['original']}")

    # Run test
    asyncio.run(test_camptocamp())
