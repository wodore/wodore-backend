"""
Provider for refuges.info images.
Uses source_id from GeoPlace source associations with organization slug 'refuges'.
"""

# Test urls:
# abri-de-Beauregard
#   https://www.refuges.info/point/6069/cabane-non-gardee/abri-de-Beauregard
#   http://192.168.1.50:8000/v1/geo/images/hut/beauregard?lang=de&radius=50&limit=20

import logging
from datetime import datetime, timezone

from django.contrib.gis.geos import Point

from .base import ImageProvider, ImageResult
from .schemas import GeoPlaceSchema
from .scoring import (
    score_metadata_completeness,
    calculate_age_penalty,
)

logger = logging.getLogger(__name__)


class RefugesInfoProvider(ImageProvider):
    """
    Provider for refuges.info images.
    Extracts images from refuges.info using the source_id from GeoPlace source associations.
    """

    source = "refugesinfo"
    cache_ttl = 14 * 24 * 3600  # 7 days
    priority = 3  # Third highest priority

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
        Fetch images from refuges.info using source IDs.

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
        logger.debug(
            f"RefugesInfoProvider.fetch() called with update_cache={update_cache}"
        )

        try:
            import httpx
            from django.conf import settings

            # 1. Check cache first
            cache_key = self._get_cache_key(lat, lon, radius, "precise")
            logger.debug(
                f"RefugesInfoProvider: update_cache={update_cache}, checking cache key {cache_key}"
            )

            if not update_cache:
                cached = await self._get_cached_results(cache_key)
                if cached is not None:
                    logger.debug(f"RefugesInfoProvider: Cache HIT for {cache_key}")
                    return cached
            else:
                logger.debug(
                    "RefugesInfoProvider: Bypassing cache due to update_cache=True"
                )

            logger.debug("RefugesInfoProvider: Cache MISS - fetching from API")

            # 2. Fetch from API
            logger.debug(
                f"RefugesInfoProvider: Checking {len(places)} places for refuges source IDs"
            )

            # Collect refuges.info source IDs from all places using the unified schema
            place_map = {}  # source_id -> GeoPlaceSchema

            for place in places:
                logger.debug(
                    f"  Checking place: {place.slug}, id={place.id}, sources={len(place.sources)}"
                )
                source_id = place.get_source_id("refuges")
                if source_id:
                    place_map[source_id] = place
                    logger.debug(
                        f"  Found refuges.info source ID {source_id} for place '{place.slug}' (id={place.id})"
                    )

            if not place_map:
                logger.debug("RefugesInfoProvider: No refuges.info source IDs found")
                await self._set_cached_results(cache_key, [])
                return []

            logger.debug(
                f"RefugesInfoProvider: Found {len(place_map)} places with refuges.info source IDs"
            )

            # Fetch images from refuges.info for each source_id
            results = []
            headers = {
                "User-Agent": getattr(
                    settings, "BOT_AGENT", "WodoreBackend/1.0 (+https://wodore.ch)"
                )
            }
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                for source_id, place in place_map.items():
                    try:
                        logger.debug(
                            f"  Fetching images from refuges.info for {source_id}..."
                        )
                        images = await self._fetch_refuges_images(
                            client, source_id, place
                        )
                        logger.debug(f"  Found {len(images)} images for {source_id}")
                        results.extend(images)
                    except Exception as e:
                        logger.error(
                            f"Error fetching refuges.info images for {source_id}: {e}"
                        )
                        continue

            logger.debug(f"RefugesInfoProvider: Found {len(results)} unique images")

            # 3. Store in cache
            logger.debug(f"RefugesInfoProvider: Caching {len(results)} results")
            await self._set_cached_results(cache_key, results)

            return results

        except Exception as e:
            logger.error(f"RefugesInfoProvider error: {e}")
            return []

    async def _fetch_refuges_images(
        self,
        client,
        source_id: str,
        place: GeoPlaceSchema,
    ) -> list[ImageResult]:
        """
        Fetch images from refuges.info for a single source ID.

        Args:
            client: HTTP client
            source_id: refuges.info source ID (hut ID)
            place: Associated GeoPlaceSchema

        Returns:
            List of ImageResult objects
        """
        try:
            from bs4 import BeautifulSoup

            url = f"https://www.refuges.info/point/{source_id}"
            logger.debug(f"  Fetching {url}...")

            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")
            comments = soup.find_all("li")

            results = []
            for comment in comments:
                try:
                    photos_div = comment.find("div", class_="photos")
                    if not photos_div:
                        continue

                    image_link = photos_div.find("a")
                    if not image_link:
                        continue

                    image_url = f"https://www.refuges.info{image_link['href']}".split(
                        "?"
                    )[0]

                    # Get date from texte_sur_image div
                    date_div = photos_div.find("div", class_="texte_sur_image")
                    if not date_div:
                        continue

                    capture_date_str_fr = date_div.text.strip()
                    capture_date = None
                    if capture_date_str_fr:
                        try:
                            import dateparser

                            capture_date = dateparser.parse(
                                capture_date_str_fr, languages=["fr"]
                            )
                        except Exception as e:
                            logger.warning(
                                f"Could not parse date: {capture_date_str_fr} for hut {source_id}: {e}"
                            )

                    # Get caption from blockquote if it exists
                    caption = ""
                    blockquote = comment.find("blockquote")
                    if blockquote:
                        caption = blockquote.text.strip()

                    # Extract author information from commentaire_metainfo div
                    author = None
                    author_url = None
                    metainfo_div = comment.find("div", class_="commentaire_metainfo")
                    if metainfo_div:
                        author_link = metainfo_div.find("a")
                        if author_link:
                            author_name = author_link.text.strip()
                            # Clean up whitespace from the author name
                            author_name = " ".join(author_name.split())
                            if author_name:
                                author = author_name
                            # Extract author URL (profile link)
                            if author_link.get("href"):
                                author_url = (
                                    f"https://www.refuges.info{author_link['href']}"
                                )

                    # Get source info
                    src_ident = f"C{image_url.split('/')[-1].split('-')[0]}"  # Extract ID from image URL
                    src_url = f"https://www.refuges.info/point/{source_id}#{src_ident}"

                    # Build attribution
                    attribution = f'via <a href="{src_url}" target="_blank" rel="nofollow">refuges.info</a>'

                    # Calculate score
                    score = self._score_refugesinfo_image(
                        has_caption=bool(caption),
                        has_author=bool(author),
                        has_date=capture_date is not None,
                        captured_at=capture_date,
                    )

                    # Create Point from GeoPlaceSchema lat/lon
                    location = Point(place.lon, place.lat, srid=4326)

                    result = ImageResult(
                        provider="refuges",  # Match organization slug in database
                        source_id=src_ident,
                        source_url=src_url,
                        image_type="flat",
                        captured_at=capture_date,
                        location=location,
                        distance_m=0,
                        license_slug="cc-by-sa-2.0-fr",  # refuges.info uses CC-BY-SA-2.0-FR
                        attribution=attribution,
                        author=author,
                        author_url=author_url,
                        url_large=image_url,
                        url_medium=None,
                        place={
                            "id": place.id,
                            "slug": place.slug,
                            "name": place.name,
                            "location": {
                                "lat": place.lat,
                                "lon": place.lon,
                            },
                        }
                        if place
                        else None,
                        score=score,
                        extra={
                            "caption": caption,
                            "refuges_id": source_id,
                        },
                    )

                    results.append(result)

                except Exception as e:
                    logger.warning(f"Error processing image from refuges.info: {e}")
                    continue

            return results

        except Exception as e:
            logger.error(
                f"HTTP error fetching refuges.info images for {source_id}: {e}"
            )
            return []

    def _score_refugesinfo_image(
        self,
        has_caption: bool,
        has_author: bool,
        has_date: bool,
        captured_at: datetime | None = None,
    ) -> int:
        """
        Score refuges.info image (0-100).

        Args:
            has_caption: Image has caption/description
            has_author: Image has author information
            has_date: Image has capture date
            captured_at: Image capture date (if available)

        Returns:
            Score from 0-100
        """
        score = 0

        # Source origin (0-50)
        # refuges.info is a curated hut database
        score += 30

        # Metadata completeness (0-25)
        score += score_metadata_completeness(
            has_description=has_caption,
            has_author=has_author,
            has_license=True,  # Always has CC-BY-SA-2.0-FR
            has_date=has_date,
        )

        # Age penalty (-50 to +5) - using global function
        if captured_at:
            days_old = (datetime.now(timezone.utc) - captured_at).days
            score += calculate_age_penalty(days_old)
        else:
            # No date available - use global penalty
            score += calculate_age_penalty(None)

        return max(0, min(score, 100))
