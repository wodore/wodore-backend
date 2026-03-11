"""
Provider for Wikidata/Wikimedia Commons images.
Uses QID from GeoPlace osm_tags to query Wikidata.
"""

import logging
from typing import Any

from django.contrib.gis.geos import Point

from .base import ImageProvider, ImageResult

logger = logging.getLogger(__name__)


class WikidataProvider(ImageProvider):
    """
    Provider for Wikidata/Wikimedia Commons images.
    Uses QID from GeoPlace osm_tags to query Wikidata.
    """

    source = "wikidata"
    cache_ttl = 7 * 24 * 60 * 60  # 7 days - Wikidata changes rarely
    priority = 2  # Second highest priority

    async def fetch(
        self,
        geoplaces: list[Any],
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
    ) -> list[ImageResult]:
        """
        Fetch images from Wikidata using QIDs.

        Args:
            geoplaces: List of GeoPlace objects within radius
            lat: Query latitude
            lon: Query longitude
            radius: Search radius in meters

        Returns:
            List of ImageResult objects
        """
        try:
            import httpx
            from asgiref.sync import sync_to_async
            from django.conf import settings

            logger.debug(
                f"🌍 WikidataProvider: Checking {len(geoplaces)} geoplaces for QIDs"
            )

            # Collect QIDs from all geoplaces (needs to be in sync context for Django ORM)
            async def collect_qids():
                qids = set()
                place_map = {}  # QID -> GeoPlace

                for place in geoplaces:
                    qid = await sync_to_async(self._extract_qid)(place)
                    if qid:
                        qids.add(qid)
                        place_map[qid] = place
                        logger.debug(f"  ✓ Found QID {qid} for place '{place.slug}'")

                return qids, place_map

            qids, place_map = await collect_qids()

            if not qids:
                logger.warning("WikidataProvider: No QIDs found in any geoplaces")
                return []

            logger.info(
                f"WikidataProvider: Found {len(qids)} unique QIDs: {list(qids)}"
            )

            # Query Wikidata for each QID
            results = []
            headers = {
                "User-Agent": getattr(
                    settings, "BOT_AGENT", "WodoreBackend/1.0 (+https://wodore.ch)"
                )
            }
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                for qid in qids:
                    try:
                        place = place_map.get(qid)
                        logger.debug(f"  🔎 Querying Wikidata for {qid}...")
                        images = await self._fetch_wikidata_images(client, qid, place)
                        logger.debug(f"  → Found {len(images)} images for {qid}")
                        results.extend(images)
                    except Exception as e:
                        logger.error(f"Error fetching Wikidata images for {qid}: {e}")
                        continue

            logger.info(f"WikidataProvider: Total images found: {len(results)}")
            return results

        except Exception as e:
            logger.error(f"WikidataProvider error: {e}")
            return []

    def _extract_qid(self, place: Any) -> str | None:
        """
        Extract Wikidata QID from GeoPlace or Hut.

        Args:
            place: GeoPlace or Hut object

        Returns:
            QID string (e.g., "Q12345") or None
        """
        place_type = place.__class__.__name__
        logger.debug(f"  _extract_qid for {place_type}: {place.slug}")

        # Try direct field first (will be added in future update)
        if hasattr(place, "wikidata_qid") and place.wikidata_qid:
            logger.debug(
                f"    ✓ Found QID via wikidata_qid field: {place.wikidata_qid}"
            )
            return place.wikidata_qid

        # Extract from osm_tags JSON field (GeoPlace)
        if hasattr(place, "osm_tags") and place.osm_tags:
            if isinstance(place.osm_tags, dict):
                qid = place.osm_tags.get("wikidata")
                if qid:
                    logger.debug(f"    ✓ Found QID via osm_tags: {qid}")
                    return qid
                else:
                    logger.debug(
                        f"    ✗ osm_tags exists but no wikidata key. Keys: {list(place.osm_tags.keys())[:10]}"
                    )

        # Try to get QID from Hut's OSM source (Hut)
        if hasattr(place, "hut_sources"):
            try:
                logger.debug(f"    Checking hut_sources for {place.slug}...")
                # Check if hut_sources is loaded
                if not hasattr(
                    place, "_prefetched_objects_cache"
                ) or "hut_sources" not in getattr(
                    place, "_prefetched_objects_cache", {}
                ):
                    logger.warning(
                        f"    ⚠ hut_sources not prefetched for {place.slug}! QID extraction may fail."
                    )

                # Log available organizations for debugging
                available_orgs = list(
                    place.hut_sources.values_list("organization__slug", flat=True)
                )
                logger.debug(f"    Available organizations: {available_orgs}")

                # Try both "osm" and "openstreetmap" as organization slugs
                osm_source = place.hut_sources.filter(
                    organization__slug__in=["osm", "openstreetmap"]
                ).first()
                if osm_source:
                    logger.debug(
                        f"    ✓ Found OSM source: {osm_source.organization.slug}"
                    )
                    if osm_source.source_data and isinstance(
                        osm_source.source_data, dict
                    ):
                        # OSM tags are in source_data
                        tags = osm_source.source_data.get("tags")
                        if tags and isinstance(tags, dict):
                            qid = tags.get("wikidata")
                            if qid:
                                logger.debug(f"    ✓ Found QID via OSM source: {qid}")
                                return qid
                            else:
                                logger.debug(
                                    f"    ✗ OSM source exists but no wikidata tag. Tags keys: {list(tags.keys())[:10]}"
                                )
                        else:
                            logger.debug(
                                f"    ✗ OSM source tags is not a dict: {type(tags)}"
                            )
                    else:
                        logger.debug(
                            f"    ✗ OSM source has no source_data or it's not a dict. Type: {type(osm_source.source_data) if osm_source.source_data else 'None'}"
                        )
                else:
                    logger.debug(f"    ✗ No OSM source found for {place.slug}")
            except Exception as e:
                logger.error(f"    ✗ Error accessing hut_sources: {e}")

        logger.debug(f"    ✗ No QID found for {place.slug}")
        return None

    async def _fetch_wikidata_images(
        self,
        client,
        qid: str,
        place: Any,
    ) -> list[ImageResult]:
        """
        Fetch images for a single QID from Wikidata.

        Args:
            client: HTTP client
            qid: Wikidata QID
            place: Associated GeoPlace

        Returns:
            List of ImageResult objects
        """
        try:
            # Use Wikidata REST API to get entity data
            url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()
            entity = data.get("entities", {}).get(qid, {})
            claims = entity.get("claims", {})

            # Get image (P18) property
            p18_claims = claims.get("P18", [])
            if not p18_claims:
                logger.debug(f"No images (P18) found for {qid}")
                return []

            results = []
            for claim in p18_claims[:10]:  # Limit to 10 images per place
                try:
                    mainsnak = claim.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue", {})
                    image_filename = datavalue.get("value")

                    if not image_filename:
                        continue

                    result = await self._build_image_result(
                        client, qid, image_filename, place
                    )
                    if result:
                        results.append(result)

                except Exception as e:
                    logger.warning(f"Error processing P18 claim for {qid}: {e}")
                    continue

            return results

        except Exception as e:
            logger.error(f"HTTP error fetching {qid}: {e}")
            return []

    async def _build_image_result(
        self,
        client,
        qid: str,
        filename: str,
        place: Any,
    ) -> ImageResult | None:
        """
        Build ImageResult for a single Wikimedia Commons image.

        Args:
            client: HTTP client
            qid: Wikidata QID
            filename: Image filename on Commons
            place: Associated GeoPlace

        Returns:
            ImageResult or None
        """
        try:
            # Build Commons URLs with proper hash path structure
            # Wikimedia Commons uses MD5 hash for directory structure: /<first_char>/<first_two_chars>/<filename>
            import hashlib
            import urllib.parse

            # Replace spaces with underscores (Commons standard)
            filename_underscore = filename.replace(" ", "_")

            # Calculate MD5 hash of the underscored filename
            md5_hash = hashlib.md5(filename_underscore.encode("utf-8")).hexdigest()

            # Build path: /<first_char>/<first_two_chars>/<url_encoded_filename>
            first_char = md5_hash[0]
            first_two = md5_hash[:2]
            filename_encoded = urllib.parse.quote(filename_underscore, safe="")

            # Proper direct URL to the image file
            direct_url = f"https://upload.wikimedia.org/wikipedia/commons/{first_char}/{first_two}/{filename_encoded}"

            wiki_file_url = (
                f"https://commons.wikimedia.org/wiki/File:{filename_encoded}"
            )
            entity_url = f"https://www.wikidata.org/wiki/{qid}"

            # Get redirected URL for Imagor (Wikimedia Commons URLs might redirect)
            try:
                import requests

                resp = requests.head(
                    direct_url,
                    allow_redirects=True,
                    headers={"User-Agent": "WodoreBackend/1.0 (+https://wodore.ch)"},
                )
                final_url = resp.url
                logger.debug(f"  Image URL: {direct_url}")
                if final_url != direct_url:
                    logger.debug(f"  Redirected to: {final_url}")
            except Exception as e:
                logger.warning(f"Could not resolve redirect for {filename}: {e}")
                final_url = direct_url

            # Get image info from Commons API
            image_info = await self._get_commons_image_info(client, filename)

            # Extract license info
            license_data = image_info.get("license", {})
            license_slug = self._normalize_license(license_data.get("url", ""))

            # Extract and clean author name
            artist = image_info.get("Artist", {}).get("value", "Unknown")
            # Remove HTML links and get just the username
            if "<a href=" in str(artist):
                # Extract text from HTML link
                import re

                match = re.search(r">([^<]+)</a>", str(artist))
                if match:
                    artist = match.group(1).strip()

            attribution = f'{artist}, <a href="{wiki_file_url}">Wikimedia Commons</a>, <a href="{license_data.get("url", "")}">{license_data.get("value", "Unknown")}</a>'

            return ImageResult(
                provider="wikidata",
                source_id=f"{qid}:{filename}",
                source_url=entity_url,
                image_type="flat",  # Most Commons images are flat
                captured_at=None,  # Not easily available
                location=place.location if place else Point(0, 0, srid=4326),
                distance_m=0,  # At the place location
                license_slug=license_slug,
                attribution=attribution,
                author=artist,
                url_large=wiki_file_url,
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
            )

        except Exception as e:
            logger.error(f"Error building image result for {filename}: {e}")
            return None

    async def _get_commons_image_info(
        self,
        client,
        filename: str,
    ) -> dict[str, Any]:
        """
        Get image metadata from Wikimedia Commons API.

        Args:
            client: HTTP client
            filename: Image filename

        Returns:
            Image metadata dict
        """
        try:
            url = "https://commons.wikimedia.org/w/api.php"
            params = {
                "action": "query",
                "titles": f"File:{filename}",
                "prop": "imageinfo",
                "iiprop": "extmetadata",
                "format": "json",
            }

            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            pages = data.get("query", {}).get("pages", {})

            for page_id, page_data in pages.items():
                if page_id == "-1":  # Not found
                    continue

                imageinfo = page_data.get("imageinfo", [])
                if imageinfo:
                    extmetadata = imageinfo[0].get("extmetadata", {})
                    return {
                        "Artist": extmetadata.get("Artist", {}),
                        "license": extmetadata.get("LicenseShortName", {}),
                    }

            return {}

        except Exception as e:
            logger.warning(f"Error getting Commons info for {filename}: {e}")
            return {}

    def _normalize_license(self, license_url: str) -> str:
        """
        Normalize license URL to slug.

        Args:
            license_url: License URL

        Returns:
            License slug (e.g., "cc-by-sa-4.0")
        """
        if not license_url:
            return "unknown"

        url_lower = license_url.lower()

        if "creativecommons.org" in url_lower:
            if "by-sa/4.0" in url_lower:
                return "cc-by-sa-4.0"
            elif "by/4.0" in url_lower:
                return "cc-by-4.0"
            elif "by-sa/3.0" in url_lower:
                return "cc-by-sa-3.0"
            elif "by/3.0" in url_lower:
                return "cc-by-3.0"
            elif "zero/1.0" in url_lower:
                return "cc0"

        return "unknown"
