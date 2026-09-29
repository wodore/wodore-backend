"""Best-effort visit counting for any model (openspec: place-visit-counter).

`record_visit(obj)` is called from the images endpoints. It deduplicates
per visitor (opaque ip+user-agent hash, cache-only, ~1 h window), buffers
the increment in the default cache, and enqueues a django-q2 flush task —
never a database write on the request path. The flush upserts one
`ObjectVisitDay` row per (content_type, object_id, day).

Counters are approximate popularity signals, not analytics — umami owns
those. No PII is stored: the visitor hash lives only in the cache.
"""

import hashlib
import logging
from datetime import date, datetime, timezone

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from server.core.models import TimeStampedModel

logger = logging.getLogger(__name__)

#: Visitor dedup window: one count per (visitor, object) per window.
VISITOR_DEBOUNCE_S = 60 * 60

#: Flush enqueue threshold: a buffered counter crossing this many hits
#: (or an object's first buffered visit) enqueues the flush task.
FLUSH_THRESHOLD = 10

#: Prefetch user agents that never represent a visitor.
SKIP_USER_AGENTS = ("python-requests", "curl/", "wget/", "headless", "googlebot")

_BUFFER_PREFIX = "visitcount:buffer"
_SEEN_PREFIX = "visitcount:seen"


class ObjectVisitDay(TimeStampedModel):
    """Daily visit count for any object (GenericForeignKey)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")

    day = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Object Visit Day"
        verbose_name_plural = "Object Visit Days"
        unique_together = (("content_type", "object_id", "day"),)
        indexes = (models.Index(fields=["day", "-count"]),)

    def __str__(self) -> str:
        return f"{self.content_type.model}#{self.object_id} {self.day}: {self.count}"


def _cache():
    from django.core.cache import cache

    return cache


def _should_skip(request) -> bool:
    if request.GET.get("update_cache"):
        return True
    ua = (request.headers.get("User-Agent") or "").lower()
    return any(marker in ua for marker in SKIP_USER_AGENTS)


def _visitor_key(request) -> str:
    ip = request.META.get("REMOTE_ADDR", "")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ua = request.headers.get("User-Agent") or ""
    raw = f"{forwarded.split(',')[0].strip() or ip}|{ua}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def record_visit(request, obj) -> bool:
    """Count a visit for obj, best-effort. Never writes to the database.

    Returns True when the visit was buffered (first hit in the visitor's
    dedup window). All failures are swallowed: counting must never break
    the observed request.
    """
    try:
        if _should_skip(request):
            return False
        ct = ContentType.objects.get_for_model(obj)
        seen_key = f"{_SEEN_PREFIX}:{_visitor_key(request)}:{ct.pk}:{obj.pk}"
        if _cache().get(seen_key):
            return False
        _cache().set(seen_key, 1, timeout=VISITOR_DEBOUNCE_S)

        day = datetime.now(tz=timezone.utc).date()
        buffer_key = f"{_BUFFER_PREFIX}:{ct.pk}:{obj.pk}:{day.isoformat()}"
        try:
            hits = _cache().incr(buffer_key)
        except ValueError:
            _cache().set(buffer_key, 1, timeout=26 * 3600)
            hits = 1

        if hits == 1 or hits % FLUSH_THRESHOLD == 0:
            from django_q.tasks import async_task

            async_task(
                "server.apps.visits.models.flush_visit_counters",
                buffer_key,
                task_name="visit-counter flush",
            )
        return True
    except Exception:
        logger.debug("visit_count_failed", exc_info=True)
        return False


def flush_visit_counters(buffer_key: str | None = None):
    """django-q2 task: read-and-clear the given buffer key, upsert its row.

    Receives the key that crossed the enqueue threshold. Visits buffered
    after the read are picked up by the next flush (each task re-checks its
    key once). Best-effort: buffers that never cross the threshold again
    linger up to their TTL — acceptable for a popularity signal.
    """
    try:
        if not buffer_key:
            return
        hits = _cache().get(buffer_key) or 0
        if hits <= 0:
            return
        _cache().delete(buffer_key)
        late = _cache().get(buffer_key) or 0  # incr raced with the delete
        _persist(buffer_key, hits + late)
        if late:
            _cache().set(buffer_key, late, timeout=26 * 3600)
    except Exception:
        logger.warning("visit_flush_failed", exc_info=True)


def _persist(buffer_key: str, hits: int):
    from django.db.models import F

    if hits <= 0:
        return
    _, _, rest = buffer_key.split(":", 2)
    ct_pk, obj_pk, day_str = rest.split(":")
    updated = ObjectVisitDay.objects.filter(
        content_type_id=int(ct_pk),
        object_id=int(obj_pk),
        day=date.fromisoformat(day_str),
    ).update(count=F("count") + hits)
    if not updated:
        ObjectVisitDay.objects.create(
            content_type_id=int(ct_pk),
            object_id=int(obj_pk),
            day=date.fromisoformat(day_str),
            count=hits,
        )


def visit_totals(model_or_ct, *, days: int = 30):
    """Visit sums per object_id for a given model (or ContentType),
    ordered by descending total over the window. Generic — knows
    nothing about which model it's counting."""
    from datetime import timedelta

    from django.db.models import Sum
    from django.db.models.functions import Coalesce

    ct = (
        model_or_ct
        if isinstance(model_or_ct, ContentType)
        else ContentType.objects.get_for_model(model_or_ct)
    )
    since = datetime.now(tz=timezone.utc).date() - timedelta(days=days)
    return (
        ObjectVisitDay.objects.filter(content_type=ct, day__gte=since)
        .values("object_id")
        .annotate(total=Coalesce(Sum("count"), 0))
        .order_by("-total")
    )


# Re-export for callers that imported from the old location.
