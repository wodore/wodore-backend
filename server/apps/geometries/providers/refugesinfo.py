"""
Provider for refuges.info images.
Uses source_id from GeoPlace source associations with organization slug 'refuges'.
"""

import logging
from typing import Any

from django.contrib.gis.geos import Point

from .base import ImageProvider, ImageResult

logger = logging.getLogger(__name__)


class RefugesInfoProvider(ImageProvider):
    """
    Provider for refuges.info images.
    Extracts images from refuges.info using the source_id from GeoPlace source associations.
    """

    source = "refugesinfo"
    cache_ttl = 7 * 24 * 60 * 60  # 7 days
    priority = 3  # Third highest priority

    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """
        Fetch images from refuges.info using source IDs.

        Args:
            geoplaces: List of GeoPlace objects within radius
            lat: Query latitude
            lon: Query longitude
            radius: Search radius in meters
            limit: Maximum number of results to return

        Returns:
            List of ImageResult objects
        """
        try:
            import httpx
            from asgiref.sync import sync_to_async
            from django.conf import settings

            logger.debug(
                f"🏔️  RefugesInfoProvider: Checking {len(geoplaces)} geoplaces for refuges source IDs"
            )

            # Collect refuges.info source IDs from all geoplaces
            async def collect_source_ids():
                place_map = {}  # source_id -> GeoPlace

                for place in geoplaces:
                    source_id = await sync_to_async(self._extract_refuges_source_id)(
                        place
                    )
                    if source_id:
                        place_map[source_id] = place
                        logger.debug(
                            f"  ✓ Found refuges.info source ID {source_id} for place '{place.slug}'"
                        )

                return place_map

            place_map = await collect_source_ids()

            if not place_map:
                logger.warning("RefugesInfoProvider: No refuges.info source IDs found")
                return []

            logger.info(
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
                            f"  🔎 Fetching images from refuges.info for {source_id}..."
                        )
                        images = await self._fetch_refuges_images(
                            client, source_id, place
                        )
                        logger.debug(f"  → Found {len(images)} images for {source_id}")
                        results.extend(images)
                    except Exception as e:
                        logger.error(
                            f"Error fetching refuges.info images for {source_id}: {e}"
                        )
                        continue

            logger.info(f"RefugesInfoProvider: Total images found: {len(results)}")
            return results

        except Exception as e:
            logger.error(f"RefugesInfoProvider error: {e}")
            return []

    def _extract_refuges_source_id(self, place: Any) -> str | None:
        """
        Extract refuges.info source ID from GeoPlace source associations.

        Args:
            place: GeoPlace object

        Returns:
            Source ID string or None
        """
        place_type = place.__class__.__name__
        logger.debug(f"  _extract_refuges_source_id for {place_type}: {place.slug}")

        # Check if place has source_associations (GeoPlace)
        if hasattr(place, "source_associations"):
            try:
                # Filter for organization with slug 'refuges'
                refuges_source = place.source_associations.filter(
                    organization__slug="refuges"
                ).first()

                if refuges_source and refuges_source.source_id:
                    logger.debug(
                        f"    ✓ Found refuges.info source ID: {refuges_source.source_id}"
                    )
                    return refuges_source.source_id
                else:
                    logger.debug(f"    ✗ No refuges.info source found for {place.slug}")

            except Exception as e:
                logger.error(f"    ✗ Error accessing source_associations: {e}")

        logger.debug(f"    ✗ No refuges.info source ID found for {place.slug}")
        return None

    async def _fetch_refuges_images(
        self,
        client,
        source_id: str,
        place: Any,
    ) -> list[ImageResult]:
        """
        Fetch images from refuges.info for a single source ID.

        Args:
            client: HTTP client
            source_id: refuges.info source ID (hut ID)
            place: Associated GeoPlace

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

                    # Get source info
                    src_ident = f"C{image_url.split('/')[-1].split('-')[0]}"  # Extract ID from image URL
                    src_url = f"https://www.refuges.info/point/{source_id}#{src_ident}"

                    # Build attribution
                    attribution = f'via <a href="{src_url}" target="_blank" rel="nofollow">refuges.info</a>'

                    result = ImageResult(
                        provider="refugesinfo",
                        source_id=src_ident,
                        source_url=src_url,
                        image_type="flat",
                        captured_at=capture_date,
                        location=place.location if place else Point(0, 0, srid=4326),
                        distance_m=0,
                        license_slug="copyright",  # refuges.info images are generally copyrighted
                        attribution=attribution,
                        author=None,  # Author info not available in current structure
                        url_large=image_url,
                        url_medium=None,
                        place={
                            "id": place.id,
                            "slug": place.slug,
                            "name": place.name_i18n,
                            "location": {
                                "lat": place.location.y,
                                "lon": place.location.x,
                            },
                        }
                        if place
                        else None,
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
