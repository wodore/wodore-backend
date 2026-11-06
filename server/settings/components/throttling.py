"""API throttling limits (openspec: api-throttling).

Rates are per client IP resolved proxy-aware (first ``X-Forwarded-For``
entry — see ``server.apps.api.throttling.ClientIp``). Counters live in
the ``throttling`` cache alias (shared backend in production).

The availability endpoints are the scraper-valuable surface (per-hut
capacities aggregated from commercial booking services), so they carry a
stacked profile: a burst limit absorbing map-viewport bursts and a daily
volume brake. Both are env-tunable without code changes.
"""

from decouple import config

#: Anti-burst limit for the availability endpoints (requests per minute
#: per client). Default 120 absorbs a cold map load plus detail browsing.
API_THROTTLE_AVAILABILITY_BURST_PER_MIN: int = config(
    "API_THROTTLE_AVAILABILITY_BURST_PER_MIN", cast=int, default=120
)

#: Daily volume limit for the availability endpoints (requests per day per
#: client). ~600 hut-detail visits/day is far above any human session and
#: far below walking all huts across a week of dates.
API_THROTTLE_AVAILABILITY_DAILY: int = config(
    "API_THROTTLE_AVAILABILITY_DAILY", cast=int, default=2000
)
