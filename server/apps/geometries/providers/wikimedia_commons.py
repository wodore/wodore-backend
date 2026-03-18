"""
Provider for Wikimedia Commons images.

Fetches images from Wikimedia Commons using multiple strategies:
1. Wikidata spatial query (P18 main image + P373 category)
2. Wikimedia Commons geosearch (fallback)

Images are scored based on metadata completeness, technical quality,
and usage signals. Images matching the GeoPlace's QID get a significant
score boost.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from django.contrib.gis.geos import Point
from django.conf import settings

from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema
from .scoring import (
    score_metadata_completeness,
    score_technical_quality,
    score_qid_match,
    calculate_age_penalty,
)

logger = logging.getLogger(__name__)


class WikimediaCommonsProvider(ImageProvider):
    """
    Provider for Wikimedia Commons images.

    Uses Wikidata SPARQL for high-quality curated images and
    Commons API geosearch as fallback.
    """

    source = "wikicommons"
    cache_ttl = 7 * 24 * 3600  # 7 days for results
    metadata_cache_ttl = (
        30 * 24 * 3600
    )  # 30 days for image metadata (dimensions, license, author)
    priority = 2  # Same as wikidata, before panoramax

    # Source type constants
    WIKIDATA_P18 = "wd_p18"  # Main image from Wikidata (highest score)
    WIKIDATA_CATEGORY = "wd_cat"  # From Wikidata category (medium score)
    GEOSEARCH = "geo"  # Commons geosearch (lowest score)

    def __init__(
        self,
        wikidata_endpoint: str = "https://query.wikidata.org/sparql",
        commons_api: str = "https://commons.wikimedia.org/w/api.php",
    ):
        """
        Initialize WikimediaCommonsProvider.

        Args:
            wikidata_endpoint: Wikidata SPARQL endpoint
            commons_api: Wikimedia Commons API endpoint
        """
        self.wikidata_endpoint = wikidata_endpoint
        self.commons_api = commons_api
        logger.debug("Initialized WikimediaCommonsProvider")

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
        Fetch images from Wikimedia Commons.

        Args:
            places: List of GeoPlaceSchema objects (with source information)
            lat: Query latitude
            lon: Query longitude
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
                    logger.debug(f"WikimediaCommonsProvider: Cache HIT for {cache_key}")
                    return cached

            logger.debug("WikimediaCommonsProvider: Cache MISS - fetching from API")

            # 2. Fetch from API
            import httpx

            results = []
            seen_titles = set()

            # Extract QIDs from places using the unified schema
            place_qids = set()
            for place in places:
                qid = place.get_wikidata_qid()
                if qid:
                    place_qids.add(qid)

            logger.debug(
                f"WikimediaCommonsProvider: Found {len(place_qids)} QIDs: {place_qids}"
            )

            # Strategy 1: Direct QID query (highest priority) - if we have QIDs
            if place_qids:
                try:
                    qid_results = await self._fetch_wikidata_by_qids(
                        place_qids, limit, httpx
                    )
                    for result in qid_results:
                        if result.source_id not in seen_titles:
                            seen_titles.add(result.source_id)
                            results.append(result)
                    logger.debug(
                        f"WikimediaCommonsProvider: Direct QID query found {len(qid_results)} images"
                    )
                except Exception as e:
                    logger.warning(f"Wikidata direct QID query failed: {e}")

            # Strategy 2: Wikidata spatial query (only if no results OR (radius > 80m AND len(results) < limit))
            # Don't run spatial query if we already have good results from direct QID lookup
            if len(results) == 0 or (radius > 80 and len(results) < limit):
                try:
                    logger.debug(
                        f"Running spatial query: radius={radius}m, current_results={len(results)}"
                    )
                    wd_results = await self._fetch_wikidata_spatial(
                        lat, lon, radius, limit, place_qids, httpx
                    )
                    for result in wd_results:
                        if result.source_id not in seen_titles:
                            seen_titles.add(result.source_id)
                            results.append(result)
                except Exception as e:
                    logger.warning(f"Wikidata spatial query failed: {e}")

            # Strategy 3: Commons geosearch (only if no results AND len(results) < limit)
            # Only run as fallback if we have NO images at all
            if len(results) == 0 and len(results) < limit:
                try:
                    logger.debug("No results yet, running Commons geosearch fallback")
                    geo_results = await self._fetch_commons_geosearch(
                        lat, lon, radius, limit, place_qids, httpx
                    )
                    for result in geo_results:
                        if result.source_id not in seen_titles:
                            seen_titles.add(result.source_id)
                            results.append(result)
                except Exception as e:
                    logger.warning(f"Commons geosearch failed: {e}")

            logger.debug(
                f"WikimediaCommonsProvider: Found {len(results)} unique images"
            )

            # 3. Store in cache
            logger.debug(f"WikimediaCommonsProvider: Caching {len(results)} results")
            await self._set_cached_results(cache_key, results)

            return results

        except Exception as e:
            logger.error(f"WikimediaCommonsProvider error: {e}")
            return []

    async def _fetch_wikidata_spatial(
        self,
        lat: float,
        lon: float,
        radius: float,
        limit: int,
        place_qids: set[str],
        httpx,
    ) -> list[ImageResult]:
        """
        Fetch images via Wikidata SPARQL spatial query.

        Returns QID + P18 image + P373 category.

        Args:
            lat: Latitude
            lon: Longitude
            place_qids: Set of known GeoPlace QIDs
            httpx: HTTP client module

        Returns:
            List of ImageResult objects
        """
        radius_km = max(1, radius / 1000)  # At least 1km

        sparql = f"""
        SELECT ?item ?itemLabel ?image ?category WHERE {{
          SERVICE wikibase:around {{
            ?item wdt:P625 ?coord.
            bd:serviceParam
              wikibase:center "Point({lon} {lat})"^^geo:wktLiteral ;
              wikibase:radius "{radius_km}" .
          }}
          ?item wdt:P31/wdt:P279* wd:Q182676.
          OPTIONAL {{ ?item wdt:P18 ?image }}
          OPTIONAL {{ ?item wdt:P373 ?category }}
          SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "de,fr,it,en"
          }}
        }} LIMIT {min(limit, 50)}
        """

        headers = {
            "User-Agent": getattr(settings, "BOT_AGENT", "WodoreBackend/1.0"),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(
                self.wikidata_endpoint, params={"query": sparql, "format": "json"}
            )
            response.raise_for_status()

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            results = []
            for binding in bindings:
                try:
                    image_uri = binding.get("image", {}).get("value")
                    if not image_uri:
                        continue

                    # Extract QID from URI
                    item_uri = binding.get("item", {}).get("value", "")
                    qid = self._extract_qid_from_uri(item_uri)

                    # Get Commons title from image URI
                    commons_title = self._extract_commons_title_from_uri(image_uri)
                    if not commons_title:
                        continue

                    # Fetch full metadata from Commons API
                    img_data = await self._fetch_commons_metadata(commons_title, client)
                    if not img_data:
                        continue

                    # Calculate score
                    matches_place_qid = qid in place_qids if qid else False
                    score = self._score_commons_image(
                        img_data,
                        source_type=WikimediaCommonsProvider.WIKIDATA_P18,
                        has_qid=bool(qid),
                        matches_place_qid=matches_place_qid,
                    )

                    # Create ImageResult
                    result = self._create_image_result(
                        commons_title, img_data, qid, score, lat, lon
                    )
                    if result:
                        results.append(result)

                except Exception as e:
                    logger.warning(f"Error parsing Wikidata result: {e}")
                    continue

            logger.debug(f"Wikidata spatial query: {len(results)} images")
            return results

    async def _fetch_wikidata_by_qids(
        self,
        qids: set[str],
        limit: int,
        httpx,
    ) -> list[ImageResult]:
        """
        Fetch images via Wikidata SPARQL using QIDs.

        This is the most reliable method when we have specific QIDs.
        We query Wikidata for the P18 (image) property for each QID.

        Args:
            qids: Set of Wikidata QIDs to query
            limit: Maximum number of results to return
            httpx: HTTP client module

        Returns:
            List of ImageResult objects
        """
        if not qids:
            return []

        # Build SPARQL query with VALUES clause for specific QIDs
        # P18 is the "image" property - the main image for a Wikidata entity
        # P373 is the "Commons category" property - category name on Wikimedia Commons
        qid_list = " ".join([f"wd:{qid}" for qid in list(qids)[:limit]])

        sparql = f"""
        SELECT ?item ?itemLabel ?image ?category WHERE {{
          VALUES ?item {{ {qid_list} }}
          OPTIONAL {{ ?item wdt:P18 ?image }}
          OPTIONAL {{ ?item wdt:P373 ?category }}
          SERVICE wikibase:label {{
            bd:serviceParam wikibase:language "de,fr,it,en"
          }}
        }}
        """

        headers = {
            "User-Agent": getattr(settings, "BOT_AGENT", "WodoreBackend/1.0"),
            "Accept": "application/json",
        }

        results = []
        categories_to_fetch = set()  # Track categories we need to fetch

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(
                self.wikidata_endpoint, params={"query": sparql, "format": "json"}
            )
            response.raise_for_status()

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            for binding in bindings:
                try:
                    # Extract QID from URI
                    item_uri = binding.get("item", {}).get("value", "")
                    qid = self._extract_qid_from_uri(item_uri)

                    # Check for P18 (main image)
                    image_uri = binding.get("image", {}).get("value")
                    if image_uri:
                        # Get Commons title from image URI
                        commons_title = self._extract_commons_title_from_uri(image_uri)
                        if commons_title:
                            # Fetch full metadata from Commons API
                            img_data = await self._fetch_commons_metadata(
                                commons_title, client
                            )
                            if img_data:
                                # Calculate score - direct QID match gets highest score
                                score = self._score_commons_image(
                                    img_data,
                                    source_type=WikimediaCommonsProvider.WIKIDATA_P18,
                                    has_qid=True,
                                    matches_place_qid=True,  # Direct match!
                                )

                                # Create ImageResult with distance 0 (exact match)
                                result = self._create_image_result(
                                    commons_title,
                                    img_data,
                                    qid,
                                    score,
                                    0.0,
                                    0.0,  # Coordinates don't matter for exact match
                                    distance_m=0.0,  # Exact QID match
                                )
                                if result:
                                    results.append(result)

                    # Check for P373 (Commons category)
                    category_binding = binding.get("category", {})
                    if category_binding.get("value"):
                        category_name = category_binding.get("value")
                        categories_to_fetch.add(category_name)

                except Exception as e:
                    logger.warning(f"Error parsing direct QID result: {e}")
                    continue

            # Now fetch all category images
            for category_name in categories_to_fetch:
                try:
                    logger.debug(
                        f"Fetching images from Commons category: {category_name}"
                    )
                    category_results = await self._fetch_commons_category_images(
                        category_name,
                        0.0,  # lat (not used for category images)
                        0.0,  # lon (not used)
                        limit,
                        httpx,
                    )
                    # Add category images (they'll have lower scores than P18)
                    for result in category_results:
                        if result.source_id not in [r.source_id for r in results]:
                            results.append(result)
                except Exception as e:
                    logger.warning(f"Error fetching category {category_name}: {e}")
                    continue

        logger.debug(
            f"Direct QID query: {len(results)} images from {len(qids)} QIDs (including categories)"
        )
        return results

    async def _fetch_commons_geosearch(
        self,
        lat: float,
        lon: float,
        radius: float,
        limit: int,
        place_qids: set[str],
        httpx,
    ) -> list[ImageResult]:
        """
        Fetch images via Commons geosearch API.

        Args:
            lat: Latitude
            lon: Longitude
            radius: Search radius in meters
            place_qids: Set of known GeoPlace QIDs
            httpx: HTTP client module

        Returns:
            List of ImageResult objects
        """
        radius_km = max(0.5, radius / 1000)  # At least 500m

        params = {
            "action": "query",
            "generator": "geosearch",
            "ggsnamespace": 6,  # File namespace
            "ggsprimary": "all",
            "ggscoord": f"{lat}|{lon}",
            "ggsradius": radius_km,
            "ggslimit": min(limit, 50),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": 400,
            "format": "json",
            "origin": "*",
        }

        headers = {
            "User-Agent": getattr(settings, "BOT_AGENT", "WodoreBackend/1.0"),
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(self.commons_api, params=params)
            response.raise_for_status()

            data = response.json()
            pages = data.get("query", {}).get("pages", {}).values()

            results = []
            for page in pages:
                try:
                    commons_title = page.get("title", "")
                    if not commons_title.startswith("File:"):
                        continue

                    # Extract metadata
                    img_data = self._parse_commons_api_response(page)

                    # Calculate score (no QID for geosearch)
                    score = self._score_commons_image(
                        img_data,
                        source_type=WikimediaCommonsProvider.GEOSEARCH,
                        has_qid=False,
                        matches_place_qid=False,
                    )

                    # Create ImageResult
                    result = self._create_image_result(
                        commons_title, img_data, None, score, lat, lon
                    )
                    if result:
                        results.append(result)

                except Exception as e:
                    logger.warning(f"Error parsing geosearch result: {e}")
                    continue

            logger.debug(f"Commons geosearch: {len(results)} images")
            return results

    async def _fetch_commons_metadata(
        self, commons_title: str, client
    ) -> dict[str, Any] | None:
        """
        Fetch detailed metadata for a Commons image.

        Args:
            commons_title: Image title (e.g., "File:Example.jpg")
            client: HTTP client

        Returns:
            Metadata dictionary or None
        """
        params = {
            "action": "query",
            "titles": commons_title,
            "prop": "imageinfo|categories",
            "iiprop": "url|extmetadata|size",
            "iiurlwidth": 400,
            "cllimit": 20,
            "format": "json",
            "origin": "*",
        }

        try:
            response = await client.get(self.commons_api, params=params)
            response.raise_for_status()

            data = response.json()
            pages = data.get("query", {}).get("pages", {})

            for page_id, page_data in pages.items():
                if page_id == "-1":  # Missing page
                    return None

                return self._parse_commons_api_response(page_data)

        except Exception as e:
            logger.warning(f"Error fetching Commons metadata: {e}")

        return None

    async def _fetch_commons_category_images(
        self,
        category_name: str,
        lat: float,
        lon: float,
        limit: int,
        httpx,
    ) -> list[ImageResult]:
        """
        Fetch images from a Wikimedia Commons category.

        Uses P373 (Commons category) property from Wikidata to find all images
        in a category, not just the main P18 image.

        Args:
            category_name: Category name (without "Category:" prefix)
            lat: Query latitude (for distance calculation)
            lon: Query longitude (for distance calculation)
            limit: Maximum number of results to return
            httpx: HTTP client module

        Returns:
            List of ImageResult objects
        """
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category_name}",
            "cmnamespace": 6,  # File namespace only
            "cmlimit": min(limit, 50),
            "format": "json",
            "origin": "*",
        }

        headers = {
            "User-Agent": getattr(settings, "BOT_AGENT", "WodoreBackend/1.0"),
        }

        results = []

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(self.commons_api, params=params)
            response.raise_for_status()

            data = response.json()
            members = data.get("query", {}).get("categorymembers", [])

            logger.debug(
                f"Commons category '{category_name}' has {len(members)} images"
            )

            for member in members[:limit]:
                try:
                    commons_title = member.get("title", "")
                    if not commons_title.startswith("File:"):
                        continue

                    # Fetch full metadata
                    img_data = await self._fetch_commons_metadata(commons_title, client)
                    if not img_data:
                        continue

                    # Calculate score (lower than P18 main image)
                    score = self._score_commons_image(
                        img_data,
                        source_type=WikimediaCommonsProvider.WIKIDATA_CATEGORY,
                        has_qid=False,  # Category images don't have direct QID
                        matches_place_qid=False,
                    )

                    # Create ImageResult
                    result = self._create_image_result(
                        commons_title, img_data, None, score, lat, lon
                    )
                    if result:
                        results.append(result)

                except Exception as e:
                    logger.warning(f"Error parsing category image: {e}")
                    continue

            logger.debug(f"Commons category query: {len(results)} images")
            return results

    def _parse_commons_api_response(self, page_data: dict) -> dict[str, Any]:
        """
        Parse Wikimedia Commons API response into metadata dict.

        Args:
            page_data: Page data from Commons API

        Returns:
            Metadata dictionary
        """
        imageinfo = page_data.get("imageinfo", [{}])[0]
        extmetadata = imageinfo.get("extmetadata", {})
        categories = page_data.get("categories", [])

        # Extract author and clean HTML
        author_raw = extmetadata.get("Artist", {}).get("value", "Unknown")

        # Extract author URL from HTML links
        author_url = None
        import re

        url_match = re.search(r'href=["\']([^"\']+)["\']', author_raw)
        if url_match:
            author_url = url_match.group(1)

        # Clean HTML and extract nice author name
        # Remove HTML tags
        author_clean = re.sub(r"<[^>]+>", "", author_raw).strip()

        # If the cleaned text looks like a URL, try to extract a nicer name
        if author_clean.startswith("http"):
            # Extract profile name from URL
            # e.g., "https://www.camptocamp.org/profiles/377/fr/alex-saunier" -> "alex-saunier"
            url_parts = author_clean.rstrip("/").split("/")
            if url_parts:
                # Get the last meaningful part
                for part in reversed(url_parts):
                    if (
                        part
                        and not part.isdigit()
                        and part
                        not in [
                            "http:",
                            "https:",
                            "www.",
                            "profiles",
                            "fr",
                            "de",
                            "en",
                            "it",
                        ]
                    ):
                        author_clean = part.replace("-", " ").replace("_", " ")
                        break

        # If still empty or looks like URL, use a generic name
        if not author_clean or author_clean.startswith("http"):
            author_clean = "Wikimedia Commons contributor"

        # Extract metadata fields
        # Get dimensions from extmetadata if available (more reliable)
        dimensions = extmetadata.get("ObjectSize", {}).get("value", "")
        width = None
        height = None
        if dimensions and "×" in dimensions:
            try:
                # Parse "1920 × 1080" format
                parts = dimensions.split("×")
                width = int(parts[0].strip())
                height = int(parts[1].strip())
            except (ValueError, IndexError):
                # Fallback to imageinfo fields
                width = imageinfo.get("width")
                height = imageinfo.get("height")
        else:
            # Fallback to imageinfo fields
            width = imageinfo.get("width")
            height = imageinfo.get("height")

        # Extract license from License.value field (not LicenseShortName)
        # Format: {"value": "cc-by-sa-3.0", "source": "commons-templates", "hidden": ""}
        license_data = extmetadata.get("License", {})
        license_slug = license_data.get("value", "")

        # Extract date - try multiple fields in order of preference
        # DateTimeOriginal: EXIF date from camera (most accurate for capture date)
        # DateTime: Date/time metadata (can be upload date or other)
        date_taken = extmetadata.get("DateTimeOriginal", {}).get(
            "value", ""
        ) or extmetadata.get("DateTime", {}).get("value", "")

        metadata = {
            "url": imageinfo.get("url"),
            "thumb_url": imageinfo.get("thumburl"),
            "width": width,
            "height": height,
            "size": imageinfo.get("size"),
            "mime": imageinfo.get("mime"),
            "author": author_clean,
            "author_url": author_url,  # Extracted URL from author HTML
            "license": license_slug,
            "license_url": extmetadata.get("LicenseUrl", {}).get("value", ""),
            "description": self._clean_html(
                extmetadata.get("ImageDescription", {}).get("value", "")
            ),
            "date_taken": date_taken,
            "categories": [cat.get("title", "") for cat in categories],
        }

        # Check for featured/quality categories
        metadata["is_featured"] = any(
            "Featured pictures" in cat for cat in metadata["categories"]
        )
        metadata["is_quality"] = any(
            "Quality images" in cat for cat in metadata["categories"]
        )

        return metadata

    def _score_commons_image(
        self,
        img_data: dict,
        source_type: str,
        has_qid: bool,
        matches_place_qid: bool,
    ) -> int:
        """
        Score Wikimedia Commons image (0-100).

        Args:
            img_data: Image metadata
            source_type: Source type (wd_p18, wd_cat, geo)
            has_qid: Image has associated Wikidata QID
            matches_place_qid: QID matches GeoPlace's QID

        Returns:
            Score from 0-100
        """
        score = 0

        # Source origin (0-50)
        source_scores = {
            WikimediaCommonsProvider.WIKIDATA_P18: 45,  # Main image from Wikidata
            WikimediaCommonsProvider.WIKIDATA_CATEGORY: 30,  # From Wikidata category (reduced from 35)
            WikimediaCommonsProvider.GEOSEARCH: 20,  # Commons geosearch (lower quality)
        }
        score += source_scores.get(source_type, 10)

        # QID match bonus (0-15)
        score += score_qid_match(has_qid=has_qid, matches_place_qid=matches_place_qid)

        # Metadata completeness (0-25)
        score += score_metadata_completeness(
            has_description=bool(img_data.get("description")),
            has_author=bool(img_data.get("author")),
            has_license=bool(img_data.get("license")),
            has_date=bool(img_data.get("date_taken")),
            has_wikidata=has_qid,
        )

        # Technical quality (0-30) - increased from 0-10
        score += score_technical_quality(
            width=img_data.get("width"),
            height=img_data.get("height"),
            mime_type=img_data.get("mime"),
            file_size=img_data.get("size"),
        )

        # Age penalty (-50 to +5) - using global function
        date_taken_str = img_data.get("date_taken")
        if date_taken_str:
            try:
                # Parse the date string to datetime object
                # Common formats: "2023-08-15 12:34:56", "15 August 2023", "2023-08-15"
                from datetime import timezone

                # Try ISO 8601 format first
                try:
                    captured_at = datetime.fromisoformat(date_taken_str)
                except ValueError:
                    # Try other common formats
                    import dateparser

                    parsed = dateparser.parse(
                        date_taken_str,
                        settings={
                            "TO_TIMEZONE": "UTC",
                            "PREFER_DATES_FROM": "past",
                        },
                    )
                    if parsed:
                        # Ensure timezone-aware datetime and set default time to 12:00
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        # If time is 00:00, assume no time was specified and use 12:00
                        if parsed.hour == 0 and parsed.minute == 0:
                            parsed = parsed.replace(hour=12, minute=0)
                        captured_at = parsed
                    else:
                        # If parsing fails, treat as no date
                        score += calculate_age_penalty(None)
                        return max(0, min(score, 100))

                # Calculate days old
                days_old = (datetime.now(timezone.utc) - captured_at).days
                score += calculate_age_penalty(days_old)
            except Exception as e:
                logger.debug(
                    f"Could not parse date '{date_taken_str}' for scoring: {e}"
                )
                score += calculate_age_penalty(None)
        else:
            # No date available - use global penalty
            score += calculate_age_penalty(None)

        return max(0, min(score, 100))

    def _create_image_result(
        self,
        commons_title: str,
        img_data: dict,
        qid: str | None,
        score: int,
        query_lat: float,
        query_lon: float,
        distance_m: float | None = None,
    ) -> ImageResult | None:
        """
        Create ImageResult from Commons metadata.

        Args:
            commons_title: Image title
            img_data: Image metadata
            qid: Associated Wikidata QID
            score: Calculated score
            query_lat: Query latitude (for distance)
            query_lon: Query longitude (for distance)
            distance_m: Pre-calculated distance in meters (optional)

        Returns:
            ImageResult or None
        """
        try:
            # Extract coordinates if available (not always in Commons)
            # For now, use query coordinates
            from math import radians, cos, sin, asin, sqrt

            def haversine_distance(lat1, lon1, lat2, lon2):
                """Calculate distance between two points in meters."""
                R = 6371000
                lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
                c = 2 * asin(sqrt(a))
                return R * c

            # Use pre-calculated distance if provided, otherwise calculate it
            if distance_m is None:
                distance_m = haversine_distance(
                    query_lat, query_lon, query_lat, query_lon
                )

            # Parse date - Wikimedia Commons uses various date formats
            # Common formats: "2023-08-15 12:34:56", "15 August 2023", "2023-08-15"
            captured_at = None
            if img_data.get("date_taken"):
                try:
                    date_str = img_data["date_taken"]

                    # Try ISO 8601 format first
                    try:
                        captured_at = datetime.fromisoformat(date_str)
                    except ValueError:
                        # Try other common formats
                        import dateparser

                        parsed = dateparser.parse(
                            date_str,
                            settings={
                                "TO_TIMEZONE": "UTC",
                                "PREFER_DATES_FROM": "past",
                            },
                        )
                        if parsed:
                            # Ensure timezone-aware datetime and set default time to 12:00
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            # If time is 00:00, assume no time was specified and use 12:00
                            if parsed.hour == 0 and parsed.minute == 0:
                                parsed = parsed.replace(hour=12, minute=0)
                            captured_at = parsed

                except Exception as e:
                    logger.debug(
                        f"Could not parse date '{img_data.get('date_taken')}': {e}"
                    )
                except (ValueError, TypeError):
                    pass

            # Build attribution
            author = img_data.get("author", "Unknown")
            attribution = (
                f'{author}, <a href="{img_data.get("url")}">Wikimedia Commons</a>'
            )
            license_url = img_data.get("license_url")
            if license_url:
                attribution += (
                    f', <a href="{license_url}">{img_data.get("license", "")}</a>'
                )

            # Normalize license
            license_slug = self._normalize_license(img_data.get("license", ""))

            # Build raw author string for deduplication
            # Concatenate all source info without formatting
            author_raw_parts = []
            if author:
                author_raw_parts.append(str(author))
            if img_data.get("author_url"):
                author_raw_parts.append(str(img_data.get("author_url")))
            author_raw_parts.append(str(img_data.get("url", "")))  # Image URL
            author_raw_parts.append(str(commons_title))  # File name
            author_raw = " ".join(filter(None, author_raw_parts))

            # Extract dimensions
            width = img_data.get("width")
            height = img_data.get("height")

            return ImageResult(
                provider="wikicommons",
                source_id=commons_title,
                source_url=f"https://commons.wikimedia.org/wiki/{commons_title}",
                image_type="flat",
                captured_at=captured_at,
                location=Point(query_lon, query_lat, srid=4326),
                distance_m=distance_m,
                license_slug=license_slug,
                attribution=attribution,
                author=author,
                author_url=img_data.get("author_url"),  # Use extracted author URL
                author_raw=author_raw,  # Raw concatenated author info for deduplication
                url_large=img_data.get("url", ""),  # Original URL only
                # url_medium is not set - we always use the original high-quality image
                width=width,
                height=height,
                place=None,  # TODO: Could look up place info from QID, but requires database query
                extra={
                    "source_url": img_data.get(
                        "url"
                    ),  # Add source URL for deduplication
                },
                score=score,
            )

        except Exception as e:
            logger.warning(f"Error creating ImageResult: {e}")
            return None

    def _extract_qid_from_uri(self, uri: str) -> str | None:
        """Extract QID from Wikidata entity URI."""
        match = re.search(r"(Q\d+)", uri)
        return match.group(1) if match else None

    def _extract_commons_title_from_uri(self, uri: str) -> str | None:
        """Extract Commons title from image URI.

        Handles two URI formats:
        - Special:FilePath (returned by Wikidata SPARQL): http://commons.wikimedia.org/wiki/Special:FilePath/B%C3%A4chlitalh%C3%BCtte.jpg
        - Wiki/File format: https://commons.wikimedia.org/wiki/File:Example.jpg

        IMPORTANT: The Commons MediaWiki API expects unencoded titles, but Special:FilePath
        returns URL-encoded filenames. We must decode them before passing to the API.

        Args:
            uri: Image URI from Wikidata

        Returns:
            Commons title (e.g., "File:Bächlitalhütte.jpg") or None
        """
        from urllib.parse import unquote

        # Try Special:FilePath format first (returned by Wikidata SPARQL)
        # Format: http://commons.wikimedia.org/wiki/Special:FilePath/B%C3%A4chlitalh%C3%BCtte.jpg
        special_match = re.search(r"/Special:FilePath/(.+)$", uri)
        if special_match:
            # Decode URL-encoded filename (e.g., %C3%A4 -> ä)
            filename = unquote(special_match.group(1))
            return f"File:{filename}"

        # Fallback to wiki/File format
        # Format: https://commons.wikimedia.org/wiki/File:Example.jpg
        wiki_match = re.search(r"/wiki/File:(.+)$", uri)
        if wiki_match:
            filename = unquote(wiki_match.group(1))
            return f"File:{filename}"

        return None

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ""
        # Simple HTML tag removal
        clean = re.sub(r"<[^>]+>", "", text)
        # Decode HTML entities
        clean = clean.replace("&amp;", "&").replace("&nbsp;", " ")
        return clean.strip()

    def _normalize_license(self, license_str: str) -> str:
        """Normalize license string to slug.

        The License field from Commons API returns values like:
        - "cc-by-sa-3.0"
        - "cc-by-4.0"
        - "cc0"

        We just pass these through directly, only normalizing if needed.
        """
        license_lower = license_str.lower()

        # If it's already in the correct format (e.g., "cc-by-sa-3.0"), use it as-is
        # License field format: {type}-{version}.{minor-version}
        if license_str and license_str.startswith("cc-"):
            return license_str

        # Fallback for public domain
        if "public domain" in license_lower or "cc0" in license_lower:
            return "pd"

        # Fallback: return the original string if we can't normalize it
        return license_str if license_str else "unknown"
