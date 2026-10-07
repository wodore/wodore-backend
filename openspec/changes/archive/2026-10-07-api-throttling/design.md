## Context

dmr ships a complete throttling framework already proven on the feedback
endpoint (`SyncThrottle`, cache keys, X-RateLimit/Retry-After headers,
OpenAPI response specs). Two production defects make it ineffective as-is:

1. **Backend**: the default Django cache is `LocMemCache` — per-process.
   dmr's `SyncDjangoCache` guard even warns about this when `DEBUG=False`;
   the feedback endpoint has been emitting that warning in production.
2. **Client key**: `dmr.throttling.cache_keys.RemoteAddr` reads
   `REMOTE_ADDR`. Behind burginfra nginx that is the proxy's address — one
   bucket for all visitors (a single scraper gets the entire limit, and
   when it trips, everyone is throttled).

The `visits` app already established this repo's proxy convention
(`server/apps/visits/models.py::_visitor_key`): first `X-Forwarded-For`
entry, `REMOTE_ADDR` fallback.

## Goals / Non-Goals

**Goals**

- Rate-limit the three availability endpoints (the scraper-valuable data)
  per real client IP, with a burst cap and a daily volume cap.
- Make throttle counters correct across workers/processes.
- Fix the feedback throttle's key and backend on the way (same machinery).
- Keep limits configurable via environment without code changes.

**Non-Goals**

- Edge/infra rate limiting (nginx `limit_req`, burginfra) — separate ops
  concern; this is application-layer only.
- Throttling the remaining read endpoints (huts, geo, meteo…) — they ride
  cheaper queries and CDN caching; the pattern established here makes that
  a follow-up one-liner per endpoint if ever needed.
- Redis — the `caches.py` TODO wants it eventually; `DatabaseCache` is the
  shared backend this repo already runs (persistent/shared aliases). The
  alias indirection makes the later swap a settings change.
- Quotas / login walls / fingerprinting — `anonymous-availability-quota`
  change.
- Authentication on any endpoint.

## Decisions

### D1 — dmr `SyncThrottle` on a dedicated `throttling` cache alias

`CACHES["throttling"]`: `DatabaseCache` (`django_cache_throttling` table,
created by the no-args `app createcachetable` deploy step) in production;
`LocMemCache` in dev/test with `allow_unsafe_cache=True` passed explicitly
(tests run with `DEBUG=False`, where dmr's default would warn). The
non-atomic get+set of `SyncDjangoCache` is documented acceptable by dmr —
slight undercount under races is fine for throttling.

### D2 — `ClientIp` cache key, visits convention

New `server/apps/api/throttling.py` defines a `ClientIp` dmr throttle cache
key: first `X-Forwarded-For` entry (comma-split, trimmed) when present, else
`REMOTE_ADDR` — byte-identical resolution to `_visitor_key`'s IP part.
Spoofing caveat is real (a client can prepend its own XFF entry) and is
closed at the proxy: nginx must **overwrite** the header
(`proxy_set_header X-Forwarded-For $remote_addr`), never append. Documented
as an ops requirement; rate limiting degrades gracefully (worst case:
per-spoofed-key buckets) unlike the current per-proxy-IP single bucket,
which is trivially gameable AND collateral-damaging.

### D3 — Stacked burst + daily throttles on availability

All three availability endpoints share one profile (env-tunable,
`API_THROTTLE_AVAILABILITY_BURST_PER_MIN` = 120,
`API_THROTTLE_AVAILABILITY_DAILY` = 2000):

- `SyncThrottle(120, Rate.minute, ClientIp)` — anti-burst.
- `SyncThrottle(2000, Rate.day, ClientIp)` — the actual scraper brake:
  ~600 hut-detail visits/day per IP is far above any human session and far
  below "walk all 300 huts × a week of dates".

Both on every endpoint of the trio — a scraper hopping between the three
endpoint shapes must respect both budgets; a legit map+detail session
(map = 1 geojson call, detail = current+trend) stays two orders of
magnitude under the caps.

### D4 — Feedback endpoint: swap backend + key, keep 5/min

Same `ClientIp` + shared backend; the 5/min limit and its existing tests
stay (they now exercise the real path).

### D5 — No API version bump; snapshot regenerated

dmr auto-documents the 429 response spec → `app api_snapshot` regenerated
and committed. Litmus test: a client pinned to the current version behaves
identically until it exceeds limits — additive standard-HTTP semantics,
not a contract change. `registry_check` still passes (no new version).

## Risks / Trade-offs

- **DB cache latency**: +2 quick cache queries per throttled request on the
  request path. Availability responses already hit postgres for GeoJSON
  aggregation; two indexed cache-table lookups are noise. Watch p95 after
  rollout.
- **Shared NAT collateral**: 2000/day per IP could pinch a large office
  behind one NAT — accepted for now; the quota change (fingerprint identity)
  is the eventual fix.
- **Cache-table culling**: `MAX_ENTRIES=100_000` for the alias; day-window
  keys expire after 24 h, minute keys after 60 s — steady-state key count
  ≈ distinct daily IPs, well under the cap.
