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
from datetime import UTC, datetime

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


def _aware(dt: datetime | None) -> datetime | None:
    """Make a provider capture time timezone-aware (naive → UTC).

    EXIF/capture times carry no zone info and providers may hand them
    through unparsed (Wikimedia ``date_taken``, stale cached results).
    Assigning a naive datetime to ``Image.capture_date`` trips Django's
    USE_TZ RuntimeWarning, so guard the model boundary here — matching the
    providers' own naive-means-UTC convention (``normalize_datetime``).
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


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


def _default_caption(source_id: str) -> str:
    """Human-friendly fallback caption from an external source id.

    ``File:Trail signs near X.jpg`` → ``Trail signs near X``.
    """
    import os
    import re

    name = os.path.splitext(source_id or "")[0]
    name = re.sub(r"^(File|Image):", "", name, flags=re.IGNORECASE)
    return name.replace("_", " ").strip()[:400]


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
                "author": (result.author or "")[:255],
                "author_url": result.author_url or "",
                "source_url": _sanitize_url(result.source_url),
                "source_url_raw": _sanitize_url(result.url_large),
                "caption_en": _default_caption(result.source_id or ""),
                "capture_date": _aware(result.captured_at),
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
            image.capture_date = _aware(result.captured_at)
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


# ---------------------------------------------------------------------------
# Background refresh (openspec pin-external-images §5) — huts and geoplaces.
# ---------------------------------------------------------------------------

#: Canonical sync radius — matches the hut page requests (the QID/category
#: strategies are radius-independent; only fallback strategies honor it).
PIN_SYNC_RADIUS_M = 50

#: A place's pins count as stale after this long; a visit then enqueues a
#: background refresh (the visitor is never delayed). External pressure stays
#: bounded by the provider-layer TTLs (7 d wikimedia / 30 d camp2camp).
PIN_REFRESH_TTL_S = 24 * 3600

#: One refresh task per place per window, regardless of visitor bursts.
PIN_REFRESH_DEBOUNCE_S = 15 * 60


def _pin_cache():
    from django.core.cache import caches

    return caches["persistent"]


def place_type_of(place) -> str:
    """'hut' or 'geoplace' for a supported place instance."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.huts.models import Hut

    if isinstance(place, Hut):
        return "hut"
    if isinstance(place, GeoPlace):
        return "geoplace"
    raise TypeError(f"Unsupported place type for pinning: {type(place)!r}")


def sync_place_images(
    place, *, radius: float = PIN_SYNC_RADIUS_M, check_origins=False, budget=None
):
    """Run the live provider pipeline for a place and pin the results.

    Background counterpart of the endpoints' lazy write-through: same
    provider call, same dedupe/score semantics. Provider-layer caches are
    respected (``update_cache=False``) — the TTL layering keeps upstream
    requests bounded (24 h pins ≤ 7 d wikimedia ≤ 30 d camp2camp).
    ``budget`` (seconds) overrides the fan-out budget for this sync — the
    request-path default trades completeness for latency, background
    sweeps may want to wait longer (``<= 0`` disables the budget).
    """
    from .providers import fetch_images_for_place, run_async

    place_type = place_type_of(place)
    results, _place_info = run_async(
        fetch_images_for_place,
        place_slug=place.slug,
        place_type=place_type,
        radius=radius,
        sources=None,
        limit=100,
        update_cache=False,
        budget=budget,
        # Command/background path: the calling thread may hold the sweep's
        # server-side cursor (``queryset.iterator()``) across this call —
        # the bridge's exit-path connection cleanup would close it.
        release_db=False,
    )
    stats = pin_place_images(place, results)
    if check_origins:
        _flag_dead_origins(place, {r.provider + ":" + r.source_id for r in results})
    return stats


def sync_place_images_task(place_type: str, slug: str):
    """django-q2 entrypoint: refresh a place's pins in the background."""
    try:
        place = _place_by_slug(place_type, slug)
        if place is None:
            logger.warning("place_sync_not_found", place_type=place_type, place=slug)
            return
        stats = sync_place_images(place)
        logger.info(
            "place_images_synced", place_type=place_type, place=slug, stats=str(stats)
        )
    except Exception:
        logger.exception("place_sync_failed", place_type=place_type, place=slug)


def _place_by_slug(place_type: str, slug: str):
    if place_type == "hut":
        from server.apps.huts.models import Hut

        return Hut.objects.filter(slug=slug, is_active=True, is_public=True).first()
    if place_type == "geoplace":
        from server.apps.geometries.models import GeoPlace

        return GeoPlace.objects.filter(
            slug=slug, is_active=True, is_public=True
        ).first()
    raise ValueError(f"Unsupported place type: {place_type}")


def maybe_enqueue_place_refresh(place) -> bool:
    """Enqueue a background refresh if the place's pins are stale.

    Never blocks or raises: the caller serves the response immediately and
    the next visitor sees the fresh pins. Returns True when a task was
    enqueued.
    """
    from django.utils import timezone

    stamped = getattr(place, "images_pinned_at", None)
    if stamped is None:
        return False  # never pinned — lazy write-through owns the first visit
    age = (timezone.now() - stamped).total_seconds()
    if age <= PIN_REFRESH_TTL_S:
        return False

    place_type = place_type_of(place)
    debounce_key = f"geoimages:pinrefresh:{place_type}:{place.slug}"
    if _pin_cache().get(debounce_key):
        return False
    try:
        from django_q.tasks import async_task

        async_task(
            "server.apps.geometries.pinning.sync_place_images_task",
            place_type,
            place.slug,
            task_name=f"pin-sync {place_type}:{place.slug}",
        )
    except Exception:
        logger.exception(
            "place_refresh_enqueue_failed", place_type=place_type, place=place.slug
        )
        return False
    _pin_cache().set(debounce_key, 1, timeout=PIN_REFRESH_DEBOUNCE_S)
    logger.info(
        "place_refresh_enqueued",
        place_type=place_type,
        place=place.slug,
        age_h=round(age / 3600, 1),
    )
    return True


def _flag_dead_origins(place, fresh_idents: set[str]) -> int:
    """Move pins with dead origins (HEAD 404/410) to review — never delete.

    A pin missing from fresh provider results is NOT considered dead (our own
    radius/category filters legitimately drop far-away images); only an
    origin that answers 404/410 is.
    """
    import requests

    from django.conf import settings
    from django.utils import timezone

    assoc_model, place_field, _inv = _association_for(place)
    flagged = 0
    assocs = assoc_model.objects.filter(
        **{place_field: place},
        image__provider_synced_at__isnull=False,
    ).exclude(image__source_ident__in=fresh_idents)
    for assoc in assocs.select_related("image"):
        image = assoc.image
        if not image.source_url_raw:
            continue
        try:
            head = requests.head(
                image.source_url_raw,
                headers={"User-Agent": settings.BOT_AGENT},
                timeout=10,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue
        if head.status_code in (404, 410):
            note = (
                f"Origin gone (HTTP {head.status_code}) at "
                f"{timezone.now():%Y-%m-%d}: {image.source_url_raw}"
            )
            image.review_comment = (image.review_comment + "\n" + note).strip()
            image.review_status = Image.ReviewStatusChoices.pending
            image.save(update_fields=["review_status", "review_comment"])
            flagged += 1
    if flagged:
        logger.info(
            "dead_origins_flagged",
            place=place.slug,
            place_type=place_type_of(place),
            count=flagged,
        )
    return flagged


#: Timeout for imagor warm-up requests (our own service, usually instant).
WARMUP_TIMEOUT_S = 20

#: First-rendered variants to pre-fetch (matches the hut page gallery/hero).
WARMUP_VARIANTS = ("sm", "lg")


def warmup_place_image_cache(
    place, *, variants: tuple[str, ...] = WARMUP_VARIANTS
) -> int:
    """Pre-fetch imagor variant URLs for a place's pins.

    Pinning is metadata-only by design (fast, provider API calls only) —
    imagor stays cold until the first visitor. This requests the
    first-rendered variants (preview/medium in each image's own
    orientation) so the hot path is instant. Pixels come from our own
    imagor; failures (dead origins return 404) are ignored.
    """
    import requests

    from .providers import post_process_images
    from .providers.wodore import WodoreProvider

    place_type = place_type_of(place)
    results = WodoreProvider(place_type=place_type)._fetch_sync(
        [], place.location.y, place.location.x, PIN_SYNC_RADIUS_M
    )
    features = post_process_images(results)
    warmed = 0
    for feature in features:
        props = feature.get("properties", {})
        urls = props.get("urls", {})
        group = "portrait" if props.get("is_portrait") else "landscape"
        for variant in variants:
            url = (urls.get(group) or {}).get(variant)
            if not url:
                continue
            try:
                response = requests.get(url, timeout=WARMUP_TIMEOUT_S)
            except requests.RequestException as e:
                logger.debug("warmup_request_failed", url=url, error=str(e))
                continue
            if response.status_code == 200:
                warmed += 1
            else:
                logger.debug(
                    "warmup_variant_unavailable",
                    url=url,
                    status=response.status_code,
                )
    if warmed:
        logger.info(
            "imagor_cache_warmed",
            place=place.slug,
            place_type=place_type,
            variants=warmed,
        )
    return warmed


def popular_places(limit: int = 20, days: int = 30):
    """Top places by visit sum over the window (visits app, place domain)."""
    from server.apps.geometries.models import GeoPlace
    from server.apps.visits.models import visit_totals

    return visit_totals(GeoPlace, days=days)[:limit]
