"""Server-side response cache for the geo-images endpoints.

Stores the serialized ``ImageCollectionResponse`` per
``(endpoint, slug-or-center, radius, sources, lang, limit)`` in the persistent
cache backend, wrapped in a freshness envelope:

- **fresh window** (``IMAGE_RESPONSE_CACHE_FRESH_SECONDS``, default 15 min):
  served directly, no provider/aggregation work.
- **stale window** (storage timeout ``IMAGE_RESPONSE_CACHE_STALE_SECONDS``,
  default 7 days): only served as *stale fallback* when recomputation fails.

Invalidation is version-based: every target (hut/place slug) carries a version
counter in the cache. Bumping the version makes all previous keys unreachable
(new keys embed the version); orphaned entries expire via the storage timeout.
"""

import time
from typing import Any

from django.conf import settings
from django.core.cache import BaseCache, caches

from .schemas import ImageCollectionResponse

_KEY_PREFIX = "geoimages:resp"
_VERSION_PREFIX = "geoimages:respver"

ResponseT = ImageCollectionResponse


def _cache() -> BaseCache:
    """Persistent cache backend (same one the provider layer uses)."""
    return caches["persistent"]


def fresh_seconds() -> int:
    """How long a cached response counts as fresh (safety-bounded)."""
    return getattr(settings, "IMAGE_RESPONSE_CACHE_FRESH_SECONDS", 15 * 60)


def stale_seconds() -> int:
    """How long a cached response is kept for stale fallback (storage TTL)."""
    return getattr(settings, "IMAGE_RESPONSE_CACHE_STALE_SECONDS", 7 * 24 * 3600)


def normalize_sources(sources: str | None) -> str:
    """Canonical form of the sources parameter so ordering does not split keys."""
    if not sources:
        return "all"
    parts = sorted({s.strip() for s in sources.split(",") if s.strip()})
    return ",".join(parts) if parts else "all"


def center_ident(lat: float, lon: float) -> str:
    """Rounded coordinate identity for the (slug-less) nearby endpoint."""
    return f"lat{round(lat, 4):.4f}:lon{round(lon, 4):.4f}"


def _version_key(endpoint: str, ident: str) -> str:
    return f"{_VERSION_PREFIX}:{endpoint}:{ident}"


def get_version(endpoint: str, ident: str) -> int:
    version = _cache().get(_version_key(endpoint, ident))
    return int(version) if version is not None else 1


def bump_version(endpoint: str, ident: str) -> int:
    """Invalidate every cached response for this target.

    ``incr`` fails on a missing key (first invalidation) — fall back to 2,
    which already differs from the implicit initial version 1.
    """
    key = _version_key(endpoint, ident)
    try:
        return int(_cache().incr(key))
    except ValueError:
        _cache().set(key, 2, timeout=None)
        return 2


def response_key(
    endpoint: str,
    ident: str,
    *,
    radius: float,
    sources: str | None,
    lang: Any,
    limit: int,
    precision: str | None = None,
) -> str:
    """Cache key embedding the target's invalidation version."""
    version = get_version(endpoint, ident)
    precision_part = f":p{precision}" if precision else ""
    return (
        f"{_KEY_PREFIX}:{endpoint}:{ident}:v{version}"
        f":r{radius:g}:s{normalize_sources(sources)}:l{lang!s}:n{limit}{precision_part}"
    )


def set_response(key: str, response: ResponseT) -> None:
    """Store a response with a freshness envelope."""
    envelope = {
        "fresh_until": time.time() + fresh_seconds(),
        "response": response.model_dump_json(exclude_unset=True),
    }
    _cache().set(key, envelope, timeout=stale_seconds())


def get_response(key: str) -> tuple[ResponseT | None, bool]:
    """Return ``(response, fresh)``; response is None when nothing is stored."""
    envelope = _cache().get(key)
    if envelope is None:
        return None, False
    response = ResponseT.model_validate_json(envelope["response"])
    return response, time.time() < float(envelope["fresh_until"])


def invalidate_for_hut(hut_slug: str) -> int:
    """Invalidate all cached responses for a hut (pin sync / curation hook)."""
    return bump_version("hut", hut_slug)


def invalidate_for_place(place_slug: str) -> int:
    """Invalidate all cached responses for a place."""
    return bump_version("place", place_slug)
