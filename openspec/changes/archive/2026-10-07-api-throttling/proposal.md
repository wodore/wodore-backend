## Why

The public `/v1` API is fully anonymous with no request-cost control: only the
feedback POST is throttled. The availability endpoints serve the most
scraper-valuable data (per-hut capacities aggregated from commercial booking
services) with nothing but browser-side `Cache-Control` as protection — one
script can walk every hut × date unbounded. The existing feedback throttle is
also broken in production on both axes: dmr's `RemoteAddr` keys on
`REMOTE_ADDR`, which is the nginx proxy IP behind burginfra (every visitor
shares one bucket), and the default `LocMemCache` keeps per-process counters
(limits silently multiply by worker count).

## What Changes

- Shared throttle state: dedicated `throttling` cache alias — `DatabaseCache`
  in production (one `app createcachetable` deploy step), LocMem in dev/test —
  so limits hold across workers. dmr's unsafe-backend guard is satisfied
  explicitly per environment.
- Proxy-aware client key: `ClientIp` cache key resolving
  `X-Forwarded-For` (first entry) with `REMOTE_ADDR` fallback — the same
  convention the `visits` app's visitor hash already uses.
- Availability endpoints get stacked throttles per client IP:
  **120/min burst AND 2000/day volume** (env-tunable), answering 429 with
  `Retry-After` + rate-limit headers via dmr.
- Feedback endpoint moves onto the shared backend + `ClientIp` (its 5/min
  limit becomes genuinely per-client instead of per-proxy-IP-per-worker).
- OpenAPI snapshot regenerated (429 documented on throttled endpoints).
  **No API version bump**: additive, standard HTTP throttling semantics —
  clients pinned to the current version see no contract change.

## Capabilities

### New Capabilities

- `api-throttling`: per-client rate limiting on public API endpoints — shared
  counter backend, client-IP resolution behind a reverse proxy, stacked
  burst + daily window limits, 429 response contract.

### Modified Capabilities

(none)

## Impact

- **Code**: `server/settings/components/caches.py` (+`throttling` alias),
  new `server/settings/components/throttling.py` (rates via env), new
  `server/apps/api/throttling.py` (`ClientIp` key + throttle profiles),
  `server/apps/availability/api.py` (3 controllers), `server/apps/feedbacks/api.py`
  (backend/key swap).
- **API**: availability endpoints may answer 429 with `Retry-After` /
  rate-limit headers; feedback unchanged in effect (5/min, now correctly keyed).
- **Ops**: one idempotent `app createcachetable`; nginx should overwrite
  (not append) `X-Forwarded-For` with the real client address so the key
  cannot be spoofed by client-supplied XFF entries.
- **Dependencies**: none new — dmr throttling already in use.
