"""
Provider for refuges.info images.

Uses the official JSON API (no HTML scraping, no redirects):

- ``GET /api/commentaires?id_point={id}`` — the point's comments, each with
  capture date, caption, author and photo references. Serves 200 directly;
  the HTML page ``/point/{id}`` 301-redirects to its canonical slug URL and
  httpx's ``raise_for_status()`` treats that redirect as an error, which
  silently killed the old scraper when the site added canonical URLs
  (staging 2026-10).
- ``GET /api/point?id={id}`` — point details; ``properties.lien`` carries the
  canonical page URL used for source deep-links (cached long-term).

Photo URLs are built deterministically from the comment id:
``/photos_points/{id}-originale.jpeg`` (large) and ``-reduite.jpeg``
(medium). The API's own ``photo-*`` fields are unreliable — they often point
at the vignette and miss the ``?`` before ``md=`` — so both the variant and
the ``md`` cache-buster are simply dropped. Verified against photos from
2013 to 2026: always ``.jpeg``, both variants answer 200.
"""

# Test urls:
# abri-de-Beauregard
#   https://www.refuges.info/point/6069/cabane-non-gardee/abri-de-Beauregard
#   http://192.168.1.50:8000/v1/geo/images/hut/beauregard?lang=de&radius=50&limit=20

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from asgiref.sync import sync_to_async

from django.contrib.gis.geos import Point

from .base import (
    CACHE_LONGTERM,
    ImageProvider,
    ImageResult,
    get_persistent_cache,
    provider_http_timeout,
)
from .schemas import GeoPlaceSchema
from .scoring import (
    calculate_age_penalty,
    score_metadata_completeness,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


class _ResponseLike(Protocol):
    """Minimal response shape the provider reads from any client."""

    def raise_for_status(self) -> Any: ...
    def json(self) -> Any: ...


class _AsyncClientLike(Protocol):
    """Client surface the provider uses (test doubles; real callers pass
    httpx.AsyncClient, accepted via the union on client params)."""

    async def get(self, url: str, params: Any) -> _ResponseLike: ...


logger = structlog.get_logger()

API_BASE = "https://www.refuges.info"


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
        logger.debug("RefugesInfoProvider.fetch() called", update_cache=update_cache)

        try:
            import httpx

            from django.conf import settings

            # 1. Check cache first
            cache_key = self._get_cache_key(lat, lon, radius, "precise")
            logger.debug(
                "Checking cache key", update_cache=update_cache, cache_key=cache_key
            )

            if not update_cache:
                cached = await self._get_cached_results(cache_key)
                if cached is not None:
                    logger.debug("Cache HIT", cache_key=cache_key)
                    return cached
            else:
                logger.debug("Bypassing cache", reason="update_cache=True")

            logger.debug("Cache MISS - fetching from API")

            # 2. Fetch from API
            logger.debug(
                "Checking places for refuges source IDs", places_count=len(places)
            )

            # Collect refuges.info source IDs from all places using the unified schema
            place_map = {}  # source_id -> GeoPlaceSchema

            for place in places:
                logger.debug(
                    "Checking place",
                    slug=place.slug,
                    id=place.id,
                    sources_count=len(place.sources),
                )
                source_id = place.get_source_id("refuges")
                if source_id:
                    place_map[source_id] = place
                    logger.debug(
                        "Found refuges.info source ID",
                        source_id=source_id,
                        place_slug=place.slug,
                        place_id=place.id,
                    )

            if not place_map:
                logger.debug("No refuges.info source IDs found")
                await self._set_cached_results(cache_key, [])
                return []

            logger.debug(
                "Found places with refuges.info source IDs", places_count=len(place_map)
            )

            # Fetch images from refuges.info for each source_id
            results = []
            headers = {
                "User-Agent": getattr(
                    settings, "BOT_AGENT", "WodoreBackend/1.0 (+https://wodore.ch)"
                )
            }
            async with (
                httpx.AsyncClient(
                    timeout=provider_http_timeout(),
                    headers=headers,
                    follow_redirects=True,  # resilience: the API answers 200, but never die on a redirect
                ) as client
            ):
                for source_id, place in place_map.items():
                    try:
                        logger.debug(
                            "Fetching images from refuges.info", source_id=source_id
                        )
                        images = await self._fetch_refuges_images(
                            client, source_id, place
                        )
                        logger.debug(
                            "Found images", count=len(images), source_id=source_id
                        )
                        results.extend(images)
                    except Exception as e:
                        logger.error(
                            "Error fetching refuges.info images",
                            source_id=source_id,
                            error=str(e),
                        )
                        continue

            logger.debug("Found unique images", count=len(results))

            # 3. Store in cache
            logger.debug("Caching results", count=len(results))
            await self._set_cached_results(cache_key, results)

            return results

        except Exception as e:
            logger.error("RefugesInfoProvider error", error=str(e))
            return []

    async def _fetch_refuges_images(
        self,
        client: AsyncClient | _AsyncClientLike,
        source_id: str,
        place: GeoPlaceSchema,
    ) -> list[ImageResult]:
        """
        Fetch images from refuges.info for a single source ID via the JSON API.

        Args:
            client: HTTP client
            source_id: refuges.info source ID (hut ID)
            place: Associated GeoPlaceSchema

        Returns:
            List of ImageResult objects
        """
        try:
            response = await client.get(
                f"{API_BASE}/api/commentaires", params={"id_point": source_id}
            )
            response.raise_for_status()
            comments = response.json()

            # The API returns a dict keyed by index ("0", "1", …) — order is
            # the page's newest-first comment order.
            if isinstance(comments, list):  # defensive: older deployments
                comments = {str(i): c for i, c in enumerate(comments)}

            canonical_url = await self._canonical_point_url(client, source_id)

            results = []
            for comment in comments.values():
                try:
                    if not any(
                        str(key).startswith("photo-") for key in (comment or {})
                    ):
                        continue
                    comment_id = comment.get("id_commentaire")
                    if not comment_id:
                        continue

                    # Deterministic URLs from the comment id — the API's own
                    # photo-* fields are unreliable (often the vignette, and
                    # the "?" before md= is missing). No md cache-buster.
                    image_url = f"{API_BASE}/photos_points/{comment_id}-originale.jpeg"
                    medium_url = f"{API_BASE}/photos_points/{comment_id}-reduite.jpeg"

                    capture_date = self._parse_capture_date(
                        comment.get("date_commentaire"), source_id
                    )
                    caption = html.unescape(
                        comment.get("texte_commentaire") or ""
                    ).strip()
                    author = (comment.get("auteur_commentaire") or "").strip() or None

                    src_ident = f"C{comment_id}"  # stable across the old scraper's pins
                    src_url = (
                        f"{canonical_url}#{src_ident}"
                        if canonical_url
                        else f"{API_BASE}/point/{source_id}#{src_ident}"
                    )

                    attribution = f'via <a href="{src_url}" target="_blank" rel="nofollow">refuges.info</a>'

                    score = self._score_refugesinfo_image(
                        has_caption=bool(caption),
                        has_author=bool(author),
                        has_date=capture_date is not None,
                        captured_at=capture_date,
                    )

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
                        author_url=None,
                        url_large=image_url,
                        url_medium=medium_url,
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
                    logger.warning(
                        "Error processing refuges.info comment",
                        error=str(e),
                        source_id=source_id,
                    )
                    continue

            return results

        except Exception as e:
            logger.error(
                "HTTP error fetching refuges.info images",
                source_id=source_id,
                error=str(e),
            )
            return []

    async def _canonical_point_url(
        self, client: AsyncClient | _AsyncClientLike, source_id: str
    ) -> str | None:
        """The point's canonical page URL (``properties.lien`` of /api/point).

        Cached long-term per point id — lien only changes when the site
        re-slugs the point. Returns None when the API fails; callers fall
        back to the short /point/{id} URL (which the site 301-redirects —
        harmless for browsers, this is attribution metadata only).
        """
        cache = get_persistent_cache()
        cache_key = self._get_metadata_cache_key(f"point_lien:{source_id}")
        cached = await sync_to_async(cache.get)(cache_key)
        if cached:
            return cached
        try:
            response = await client.get(
                f"{API_BASE}/api/point", params={"id": source_id}
            )
            response.raise_for_status()
            features = response.json().get("features", [])
            lien = (
                (features[0].get("properties") or {}).get("lien") if features else None
            )
        except Exception as e:
            logger.debug(
                "Could not fetch refuges.info point URL",
                source_id=source_id,
                error=str(e),
            )
            return None
        if lien:
            await sync_to_async(cache.set)(cache_key, lien, CACHE_LONGTERM)
        return lien

    def _parse_capture_date(self, date_str: str | None, source_id: str):
        """Parse ``date_commentaire`` (e.g. '2026-08-16 18:14:02.018925+02').

        ``datetime.fromisoformat`` handles the site's offset format directly;
        naive values are treated as UTC (provider-wide convention).
        """
        if not date_str:
            return None
        try:
            capture_date = datetime.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            logger.warning(
                "Could not parse date", date_str=date_str, source_id=source_id
            )
            return None
        if capture_date.tzinfo is None:
            capture_date = capture_date.replace(tzinfo=timezone.utc)
        return capture_date

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
