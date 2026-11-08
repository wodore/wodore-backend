"""Read-only refuges.info comment provider (openspec: reviews-mangrove).

Serves community hut comments from https://www.refuges.info as reviews
alongside Mangrove reviews. Verified live 2026-11-08:

* ``GET {base}/api/commentaires?id_point={id}&format=json`` — a dict
  keyed by index (``{"0": {...}}``, newest first; older deployments
  returned a list), each item with ``id_commentaire``,
  ``auteur_commentaire``, ``date_commentaire`` (``2026-08-16
  18:14:02.018925+02``), ``texte_commentaire`` (HTML-escaped) and
  optional ``photo-*`` fields.
* Every response envelope carries ``copyright … CC By-Sa 2.0`` — the
  data's license (per-review on everything we serve).

Hard boundaries: READ-ONLY merge with attribution. Comments are NEVER
re-published into Mangrove (CC BY-SA cannot be relicensed to the
dataset's CC-BY-4.0, and MaReSt reviews must be signed by their
authors). Failures degrade to an empty list — the Mangrove listing
must never 503 because the secondary source is down.
"""

import datetime
import html
import re
import time
import typing as t

import httpx
import structlog

from django.conf import settings
from django.core.cache import caches

logger = structlog.get_logger(__name__)

#: Shared cross-worker cache (Opus review B6) + failure back-pressure.
_cache = caches["shared"]
_NEGATIVE_TTL = 60  # seconds a failing provider stays "down" for this point

#: Served per review (user-facing license + source attribution).
SOURCE = "refuges.info"
LICENSE = "CC BY-SA 2.0 FR"

_tag_re = re.compile(r"<[^>]+>")

_client: "RefugesInfoClient | None" = None


def refuges_client() -> "RefugesInfoClient":
    """The process-wide provider client (tests monkeypatch this)."""
    global _client
    if _client is None:
        _client = RefugesInfoClient()
    return _client


class RefugeComment(t.NamedTuple):
    """One parsed refuges.info comment."""

    signature: str
    author: str | None
    created: datetime.datetime
    text: str


def _parse_date(raw: str) -> datetime.datetime | None:
    """Tolerant parser for ``2026-08-16 18:14:02.018925+02``."""
    value = raw.strip()
    # Normalize a bare ±HH offset to ±HH:00 for fromisoformat.
    if value and re.search(r"[+-]\d{2}$", value):
        value += ":00"
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _clean_text(raw: str) -> str:
    """HTML-unescape and strip tags; collapse whitespace."""
    without_tags = _tag_re.sub(" ", html.unescape(raw or ""))
    return " ".join(without_tags.split())


class RefugesInfoClient:
    """Sync httpx client for the commentaires endpoint (the only one)."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or settings.MANGROVE_REFUGES_INFO_API_BASE

    def list_comments(self, point_id: str) -> list[RefugeComment]:
        """The point's comments, oldest→newest; ``[]`` on any failure."""
        key = f"reviews:refuges:{point_id}"
        cached = _cache.get(key)
        if cached is not None:
            return [
                RefugeComment(
                    signature=c[0],
                    author=c[1],
                    created=datetime.datetime.fromisoformat(c[2]),
                    text=c[3],
                )
                for c in cached
            ]
        if _cache.get(f"{key}:down"):
            return []  # recent failure — negative-cached (Opus B6)
        started = time.monotonic()
        try:
            response = httpx.get(
                f"{self._base_url}/api/commentaires",
                params={"id_point": point_id, "format": "json"},
                timeout=httpx.Timeout(
                    settings.MANGROVE_TIMEOUT_READ,
                    connect=settings.MANGROVE_TIMEOUT_CONNECT,
                ),
                headers={"User-Agent": "wodore-backend (reviews integration)"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "refuges_info_unavailable",
                point_id=point_id,
                error=type(exc).__name__,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            _cache.set(f"{key}:down", True, _NEGATIVE_TTL)
            return []
        comments = parse_comments(payload)
        _cache.set(
            key,
            [(c.signature, c.author, c.created.isoformat(), c.text) for c in comments],
            settings.MANGROVE_CACHE_TTL_LIST,
        )
        logger.info(
            "refuges_info_request",
            point_id=point_id,
            comments=len(comments),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return comments


def parse_comments(payload: t.Any) -> list[RefugeComment]:
    """Dict-by-index (current) or list (older) → parsed comments."""
    items: list[t.Any]
    if isinstance(payload, dict):
        items = [
            payload[key]
            for key in sorted(
                payload.keys(), key=lambda k: int(k) if str(k).isdigit() else 0
            )
            if key != "copyright"
        ]
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    out: list[RefugeComment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        comment_id = str(item.get("id_commentaire") or "").strip()
        text = _clean_text(str(item.get("texte_commentaire") or ""))
        if not comment_id or not text:
            continue
        author = str(item.get("auteur_commentaire") or "").strip() or None
        created = _parse_date(str(item.get("date_commentaire") or ""))
        out.append(
            RefugeComment(
                signature=f"refuges-info:{comment_id}",
                author=author,
                created=created or datetime.datetime.now(tz=datetime.UTC),
                text=text,
            )
        )
    out.sort(key=lambda c: c.created)
    return out


def point_id_for_hut(hut: "t.Any") -> str | None:
    """The hut's refuges.info point id from its HutSource (org ``refuges``)."""
    from server.apps.huts.models import HutSource

    source = (
        HutSource.objects.filter(hut=hut, organization__slug="refuges", is_current=True)
        .order_by("-created")
        .only("source_id")
        .first()
    )
    if source is None or not str(source.source_id).strip():
        return None
    return str(source.source_id).strip()


def comments_for_hut(hut: "t.Any", cached_only: bool = False) -> list[RefugeComment]:
    """The hut's refuges.info comments (cached, failure-tolerant).

    ``cached_only`` skips a cold fetch (map-badge batches — no provider
    fan-out on the hot path, Opus review B6).
    """
    if not settings.MANGROVE_REFUGES_INFO_ENABLED:
        return []
    point_id = point_id_for_hut(hut)
    if point_id is None:
        return []
    if cached_only and _cache.get(f"reviews:refuges:{point_id}") is None:
        return []
    return refuges_client().list_comments(point_id)


def point_url(point_id: str) -> str:
    """Attribution link to the refuge's page (per-review ``link``)."""
    return f"{settings.MANGROVE_REFUGES_INFO_API_BASE}/point/{point_id}"
