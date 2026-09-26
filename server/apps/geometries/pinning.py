"""Pin external provider results as ``Image`` rows.

Materializes provider ``ImageResult`` objects into the existing Image model
(metadata only — the file field stays empty, pixels keep streaming from the
origin through imagor). Deduplicated by ``source_ident`` across syncs; the
place association carries the provider score, which manual curation may
override (syncs never overwrite an existing association's score). Works for
both Huts and GeoPlaces — the same external image can be pinned to several
places with independent per-place scores.

See openspec change ``pin-external-images``.
"""

from dataclasses import dataclass

import structlog

from django.utils import timezone

from server.apps.geometries.models import GeoPlaceImageAssociation
from server.apps.huts.models import HutImageAssociation
from server.apps.images.models import Image
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization

from .image_response_cache import invalidate_for_hut, invalidate_for_place
from .providers.base import ImageResult

logger = structlog.get_logger()

#: Provider slug that marks internal results (uploads / hut import) — those
#: images are already associated with the place and must never be re-pinned.
INTERNAL_PROVIDER_SLUG = "wodore"


@dataclass
class PinStats:
    """Outcome of a pin run."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    associations_created: int = 0

    def __str__(self) -> str:  # pragma: no cover - logging convenience
        return (
            f"created={self.created} updated={self.updated} "
            f"skipped={self.skipped} new_links={self.associations_created}"
        )


def _source_ident(result: ImageResult) -> str:
    """Stable dedupe key for a provider result."""
    return f"{result.provider}:{result.source_id}"[:512]


def _sanitize_url(url: str | None) -> str:
    """Make a provider URL storable (URLField) and cache-stable.

    Providers hand us partially-unencoded URLs (e.g. Commons file titles with
    spaces/umlauts) and Wikimedia appends ``utm_*`` tracking params to thumb
    URLs — those would fail admin validation and bust imagor's cache keys
    whenever the params change. Encodes the path (preserving existing
    percent-escapes) and strips ``utm_*`` query parameters.
    """
    from urllib.parse import quote, urlsplit, urlunsplit

    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = quote(parts.path, safe="/%:")
    query = ""
    if parts.query:
        kept = [
            pair
            for pair in parts.query.split("&")
            if pair and not pair.lower().startswith("utm_")
        ]
        query = "&".join(kept)
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def _license_for(slug: str) -> License:
    license_obj, _created = License.objects.get_or_create(
        slug=slug,
        # Provider results are published at the origin — publication is the
        # point of pinning. (License.no_publication defaults to True, which
        # would exclude every pin from serving.)
        defaults={"name": slug, "fullname": slug, "no_publication": False},
    )
    return license_obj


def _org_for(slug: str) -> Organization:
    org, _created = Organization.objects.get_or_create(
        slug=slug[:50], defaults={"name_en": slug}
    )
    return org


def _merge_image_meta(image: Image, result: ImageResult) -> dict:
    """Refresh provider metadata while preserving curated keys (focal/crop)."""
    meta = dict(image.image_meta or {})
    if result.width:
        meta["width"] = result.width
    if result.height:
        meta["height"] = result.height
    meta["provider_score"] = result.score
    return meta


def _merge_image_meta_from_result(result: ImageResult) -> dict:
    meta: dict = {"provider_score": result.score}
    if result.width:
        meta["width"] = result.width
    if result.height:
        meta["height"] = result.height
    return meta


def _association_for(place):
    """Resolve (association model, place FK field name, cache invalidator)."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut

    if isinstance(place, Hut):
        return HutImageAssociation, "hut", invalidate_for_hut
    if isinstance(place, GeoPlace):
        return GeoPlaceImageAssociation, "geo_place", invalidate_for_place
    raise TypeError(f"Unsupported place type for pinning: {type(place)!r}")


def pin_place_images(place, results: list[ImageResult]) -> PinStats:
    """Pin provider results to a place (Hut or GeoPlace).

    Existing pins get their mutable fields refreshed (URLs can change when a
    file is re-uploaded at the origin); association scores are only ever set
    once — manual curation survives later syncs. Internal (``wodore``)
    results are skipped: those images already live in our DB. The same image
    can be pinned to several places; scores are per association.
    """
    assoc_model, place_field, invalidate = _association_for(place)
    stats = PinStats()
    now = timezone.now()

    for result in results:
        if result.provider == INTERNAL_PROVIDER_SLUG:
            stats.skipped += 1
            continue

        ident = _source_ident(result)
        org = _org_for(result.provider)
        license_obj = _license_for(result.license_slug)

        image, created = Image.objects.get_or_create(
            source_ident=ident,
            defaults={
                "source_org": org,
                "license": license_obj,
                "author": result.author or "",
                "author_url": result.author_url or "",
                "source_url": _sanitize_url(result.source_url),
                "source_url_raw": _sanitize_url(result.url_large),
                "caption_en": (result.source_id or "")[:400],
                "capture_date": result.captured_at,
                "provider_synced_at": now,
                "image_meta": _merge_image_meta_from_result(result),
            },
        )
        if created:
            stats.created += 1
        else:
            # Refresh mutable fields; keep curated fields (review_status,
            # focal/crop via meta merge, tags, captions) untouched.
            image.source_url_raw = _sanitize_url(result.url_large)
            sanitized_source = _sanitize_url(result.source_url)
            if sanitized_source:
                image.source_url = sanitized_source
            image.source_org = org
            image.license = license_obj
            image.capture_date = result.captured_at
            image.provider_synced_at = now
            image.image_meta = _merge_image_meta(image, result)
            image.save()
            stats.updated += 1

        assoc, assoc_created = assoc_model.objects.get_or_create(
            image=image,
            defaults={"score": min(max(result.score, 0), 32767)},
            **{place_field: place},
        )
        if assoc_created:
            stats.associations_created += 1
        # Never overwrite an existing score — manual curation wins.

    if hasattr(place, "images_pinned_at"):
        place.images_pinned_at = now
        place.save(update_fields=["images_pinned_at"])
    invalidate(place.slug)
    logger.info(
        "place_images_pinned",
        place_type=type(place).__name__,
        place=place.slug,
        created=stats.created,
        updated=stats.updated,
        skipped=stats.skipped,
        new_links=stats.associations_created,
    )
    return stats


def place_has_visible_pins(place) -> bool:
    """Whether the place has at least one servable pinned/associated image."""
    assoc_model, place_field, _invalidator = _association_for(place)
    return (
        assoc_model.objects.filter(
            **{
                place_field: place,
                "image__is_active": True,
                "image__review_status": Image.ReviewStatusChoices.approved,
            }
        )
        .exclude(image__license__no_publication=True)
        .exists()
    )
