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
from datetime import datetime
from typing import Any

from django.contrib.gis.geos import Point
from django.conf import settings

from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema
from .scoring import (
    score_metadata_completeness,
    score_technical_quality,
    score_qid_match,
)

logger = logging.getLogger(__name__)


class WikimediaCommonsProvider(ImageProvider):
    """
    Provider for Wikimedia Commons images.

    Uses Wikidata SPARQL for high-quality curated images and
    Commons API geosearch as fallback.
    """

    source = "wikimedia_commons"
    cache_ttl = 7 * 24 * 3600  # 14 days
    priority = 2  # Same as wikidata, before panoramax

    # Source type constants
    WIKIDATA_P18 = "wd_p18"  # Main image from Wikidata
    WIKIDATA_CATEGORY = "wd_cat"  # From Wikidata category
    GEOSEARCH = "geo"  # Commons geosearch

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

            # Strategy 2: Wikidata spatial query (if we still need more results)
            if len(results) < limit:
                try:
                    wd_results = await self._fetch_wikidata_spatial(
                        lat, lon, radius, limit, place_qids, httpx
                    )
                    for result in wd_results:
                        if result.source_id not in seen_titles:
                            seen_titles.add(result.source_id)
                            results.append(result)
                except Exception as e:
                    logger.warning(f"Wikidata spatial query failed: {e}")

            # Strategy 3: Commons geosearch (fallback if low results)
            if len(results) < 10:
                try:
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
        qid_list = " ".join([f"wd:{qid}" for qid in list(qids)[:limit]])

        sparql = f"""
        SELECT ?item ?itemLabel ?image WHERE {{
          VALUES ?item {{ {qid_list} }}
          OPTIONAL {{ ?item wdt:P18 ?image }}
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

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(
                self.wikidata_endpoint, params={"query": sparql, "format": "json"}
            )
            response.raise_for_status()

            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])

            for binding in bindings:
                try:
                    image_uri = binding.get("image", {}).get("value")
                    if not image_uri:
                        item_uri = binding.get("item", {}).get("value", "")
                        qid = self._extract_qid_from_uri(item_uri)
                        logger.debug(f"QID {qid} has no P18 image")
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

                except Exception as e:
                    logger.warning(f"Error parsing direct QID result: {e}")
                    continue

        logger.debug(f"Direct QID query: {len(results)} images from {len(qids)} QIDs")
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

        # Extract metadata fields
        metadata = {
            "url": imageinfo.get("url"),
            "thumb_url": imageinfo.get("thumburl"),
            "width": imageinfo.get("width"),
            "height": imageinfo.get("height"),
            "size": imageinfo.get("size"),
            "mime": imageinfo.get("mime"),
            "author": self._clean_html(
                extmetadata.get("Artist", {}).get("value", "Unknown")
            ),
            "license": extmetadata.get("LicenseShortName", {}).get("value", ""),
            "license_url": extmetadata.get("LicenseUrl", {}).get("value", ""),
            "description": self._clean_html(
                extmetadata.get("ImageDescription", {}).get("value", "")
            ),
            "date_taken": extmetadata.get("DateTimeOriginal", {}).get("value", ""),
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
            WikimediaCommonsProvider.WIKIDATA_P18: 50,
            WikimediaCommonsProvider.WIKIDATA_CATEGORY: 30,
            WikimediaCommonsProvider.GEOSEARCH: 10,
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

        # Technical quality (0-10)
        score += score_technical_quality(
            width=img_data.get("width"),
            height=img_data.get("height"),
            mime_type=img_data.get("mime"),
            file_size=img_data.get("size"),
        )

        return min(score, 100)

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

            # Parse date
            captured_at = None
            if img_data.get("date_taken"):
                try:
                    captured_at = datetime.fromisoformat(img_data["date_taken"])
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

            # Extract dimensions
            width = img_data.get("width")
            height = img_data.get("height")

            return ImageResult(
                provider="wikimedia_commons",
                source_id=commons_title,
                source_url=img_data.get("url"),
                image_type="flat",
                captured_at=captured_at,
                location=Point(query_lon, query_lat, srid=4326),
                distance_m=distance_m,
                license_slug=license_slug,
                attribution=attribution,
                author=author,
                author_url=None,
                url_large=img_data.get("url", ""),
                url_medium=img_data.get("thumb_url"),
                width=width,
                height=height,
                place={"qid": qid} if qid else None,
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
        """Extract Commons title from image URI."""
        # URI format: https://commons.wikimedia.org/wiki/File:Example.jpg
        match = re.search(r"File:(.+)$", uri)
        return f"File:{match.group(1)}" if match else None

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
        """Normalize license string to slug."""
        license_lower = license_str.lower()

        if "cc-by-sa-4.0" in license_lower or "by-sa/4.0" in license_lower:
            return "cc-by-sa-4.0"
        elif "cc-by-4.0" in license_lower or "by/4.0" in license_lower:
            return "cc-by-4.0"
        elif "public domain" in license_lower:
            return "pd"
        else:
            return "unknown"
