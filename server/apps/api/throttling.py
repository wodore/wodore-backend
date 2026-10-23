"""Shared throttling primitives for the public API (openspec: api-throttling).

- ``ClientIp`` — proxy-aware throttle cache key: the first
  ``X-Forwarded-For`` entry with ``REMOTE_ADDR`` fallback, the same
  convention as the visits visitor hash. Behind burginfra nginx,
  ``REMOTE_ADDR`` alone is the proxy address, which would put every
  visitor in one bucket (dmr's ``RemoteAddr`` is therefore not used here).
  The header must be trustworthy: nginx has to overwrite (not append)
  ``X-Forwarded-For`` with the real client address.
- ``throttle_backend()`` — ``SyncDjangoCache`` on the shared
  ``throttling`` cache alias, so counters hold across workers. In
  dev/test the alias intentionally resolves to LocMem; that is declared
  via ``allow_unsafe_cache`` instead of tripping dmr's guard.
- Availability profile — stacked burst + daily throttles per client IP
  (limits from ``server.settings.components.throttling``).
"""

import dataclasses
from typing import TYPE_CHECKING

from dmr.throttling import Rate, SyncThrottle
from dmr.throttling.backends import SyncDjangoCache
from dmr.throttling.cache_keys import BaseThrottleCacheKey
from typing_extensions import override

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends import dummy, locmem

if TYPE_CHECKING:
    from dmr.controller import Controller
    from dmr.endpoint import Endpoint
    from dmr.serializer import BaseSerializer


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class ClientIp(BaseThrottleCacheKey):
    """First ``X-Forwarded-For`` entry, ``REMOTE_ADDR`` fallback."""

    runs_before_auth: bool = True
    name: str = "ClientIp"

    @override
    def __call__(
        self,
        endpoint: "Endpoint",
        controller: "Controller[BaseSerializer]",
    ) -> str | None:
        request = controller.request
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR")


def throttle_backend() -> SyncDjangoCache:
    """Shared throttle storage on the ``throttling`` cache alias.

    ``allow_unsafe_cache`` is derived from the alias itself: process-local
    backends (dev/test) are explicitly declared; shared backends keep
    dmr's production guard active.
    """
    unsafe = isinstance(caches["throttling"], (locmem.LocMemCache, dummy.DummyCache))
    return SyncDjangoCache(cache_name="throttling", allow_unsafe_cache=unsafe or None)


#: Anti-burst: absorbs cold map loads and detail browsing, blocks floods.
AVAILABILITY_BURST_THROTTLE = SyncThrottle(
    settings.API_THROTTLE_AVAILABILITY_BURST_PER_MIN,
    Rate.minute,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)

#: Volume brake: pacing under the burst limit for a full day still stops
#: at this many requests — the actual scraper ceiling.
AVAILABILITY_DAILY_THROTTLE = SyncThrottle(
    settings.API_THROTTLE_AVAILABILITY_DAILY,
    Rate.day,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)

#: Stacked profile for every availability endpoint.
AVAILABILITY_THROTTLES: list[SyncThrottle] = [
    AVAILABILITY_BURST_THROTTLE,
    AVAILABILITY_DAILY_THROTTLE,
]

#: Feedback POST: public, stores a row and mails admins — brute-force/spam
#: protection (unchanged 5/min; moved onto the shared backend + client key).
FEEDBACK_THROTTLE = SyncThrottle(
    5,
    Rate.minute,
    cache_key=ClientIp(),
    backend=throttle_backend(),
)
