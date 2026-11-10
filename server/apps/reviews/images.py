"""Mangrove review photos as a standard image-provider source (design D9).

Serves the images attached to a hut's Mangrove reviews through the
geometries image pipeline — the hut gallery endpoint fans out to this
provider like any other, so review photos get imagor variants,
license rows (CC-BY-4.0 per review metadata), attribution (reviewer
nickname) and dedup scoring for free.

Fidelity rules mirror the review listings: only reviews whose subject
geo-matches the hut's subject, blacklist-hidden signatures excluded,
`MANGROVE_ENABLED` kill-switch respected, failures degrade to an empty
result (a provider must never raise).
"""

import datetime
import typing as t

import structlog
from asgiref.sync import sync_to_async

from django.conf import settings
from django.contrib.gis.geos import Point

from server.apps.geometries.providers.base import (
    CACHE_SHORT,
    ImageProvider,
    ImageResult,
    _generate_license_slug,
)

from .client import parse_geo_subject, subject_geo_matches

logger = structlog.get_logger(__name__)


def _review_image_results(slug: str, limit: int) -> list[ImageResult]:
    """Sync core: the hut's review photos as ImageResults (never raises)."""
    from server.apps.huts.models import Hut

    from .models import ReviewBlacklist
    from .services import build_geo_subject, resolve_review_name

    hut = (
        Hut.objects.filter(slug=slug, is_active=True, is_public=True)
        .only("slug", "location", "name")
        .first()
    )
    if hut is None:
        return []
    subject = build_geo_subject(
        hut.location.y, hut.location.x, resolve_review_name(hut)
    )
    try:
        from .services import client as services_client

        response = services_client().list_reviews(subject)
    except Exception as exc:
        logger.warning(
            "mangrove_images_unavailable", slug=slug, error=type(exc).__name__
        )
        return []
    blacklisted = set(ReviewBlacklist.objects.values_list("signature", flat=True))
    import html as _html

    from .services import _effective_subject, _image_src_allowed

    results: list[ImageResult] = []
    for item in response.reviews:
        from .services import _effective_signature as _eff_sig

        _effective = _eff_sig(item)
        if item.payload.action not in (None, "edit"):
            continue
        if item.signature in blacklisted or _effective in blacklisted:
            continue
        if not subject_geo_matches(_effective_subject(item), subject):
            continue
        metadata = item.payload.metadata or {}
        author = (
            metadata.get("nickname")
            if isinstance(metadata.get("nickname"), str)
            else None
        )
        license_slug = _generate_license_slug(
            str(metadata.get("license") or "CC-BY-4.0")
        )
        captured = datetime.datetime.fromtimestamp(item.payload.iat, tz=datetime.UTC)
        parsed = parse_geo_subject(item.payload.sub)
        location = (
            Point(parsed.lon, parsed.lat)
            if parsed
            else Point(hut.location.x, hut.location.y)
        )
        for index, image in enumerate(item.payload.images or []):
            if not _image_src_allowed(image.src):
                continue  # SSRF guard: same allowlist as the list path (Opus B1)
            safe_author = _html.escape(author) if author else "Anonymous"
            results.append(
                ImageResult(
                    provider="open_reviews",
                    source_id=f"{item.signature}:{index}",
                    source_url=None,
                    image_type="flat",
                    captured_at=captured,
                    location=location,
                    distance_m=0,
                    license_slug=license_slug,
                    attribution=(
                        f"{safe_author}, CC-BY-4.0 via "
                        '<a href="https://mangrove.reviews" target="_blank" '
                        'rel="nofollow">Mangrove</a>'
                    ),
                    author=author,
                    author_url=None,
                    url_large=image.src,
                    place={
                        "id": hut.pk,
                        "slug": hut.slug,
                        "name": hut.name,
                        "location": {"lat": hut.location.y, "lon": hut.location.x},
                    },
                )
            )
            if len(results) >= limit:
                return results
    return results


class MangroveProvider(ImageProvider):
    """Review photos from the open Mangrove dataset."""

    source = "open_reviews"
    cache_ttl = CACHE_SHORT  # reviews change; 24 h
    priority = 4

    async def fetch(
        self,
        places: "list[t.Any]",
        lat: float,
        lon: float,
        radius: float,
        limit: int = 100,
        update_cache: bool = False,
    ) -> "list[ImageResult]":
        if not settings.ORA_ENABLED:
            return []
        cache_key = self._get_cache_key(lat, lon, radius)
        if not update_cache:
            cached = await self._get_cached_results(cache_key)
            if cached is not None:
                return cached
        results: list[ImageResult] = []
        for place in places:
            slug = getattr(place, "slug", None)
            if not slug:
                continue
            try:
                results.extend(
                    await sync_to_async(_review_image_results)(
                        slug, limit - len(results)
                    )
                )
            except Exception as exc:
                logger.warning(
                    "mangrove_images_failed", slug=slug, error=type(exc).__name__
                )
            if len(results) >= limit:
                break
        await self._set_cached_results(cache_key, results)
        return results
