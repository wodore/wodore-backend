## 1. Throttle infrastructure

- [x] 1.1 Add `throttling` cache alias in `server/settings/components/caches.py`: DatabaseCache (`django_cache_throttling`, `MAX_ENTRIES=100_000`) for production/staging (override in `production.py`; staging inherits via `import *`), LocMemCache otherwise
- [x] 1.2 Create `server/settings/components/throttling.py`: availability burst (`API_THROTTLE_AVAILABILITY_BURST_PER_MIN`, default 120) and daily (`API_THROTTLE_AVAILABILITY_DAILY`, default 2000) settings via decouple config; wire component into `server/settings/__init__.py` after `caches.py`
- [x] 1.3 Create `server/apps/api/throttling.py`: `ClientIp` dmr cache-key class (first XFF entry, `REMOTE_ADDR` fallback — visits convention) and `throttle_backend()` returning `SyncDjangoCache(cache_name="throttling", ...)` with `allow_unsafe_cache` derived from the alias itself

## 2. Endpoint wiring

- [x] 2.1 Add stacked throttles (burst + daily) to the three controllers in `server/apps/availability/api.py`
- [x] 2.2 Swap `RemoteAddr`/default backend → `ClientIp`/shared backend on the feedback POST in `server/apps/feedbacks/api.py` (5/min unchanged)

## 3. Tests

- [x] 3.1 Availability throttling tests (`tests/apps/availability/test_throttling.py`): probe controller (same `ClientIp` + shared backend, small limit) covering burst trip → 429 + `Retry-After` + `X-RateLimit-*` + `{"code": "throttled"}` body; XFF bucket separation; first-entry-wins; `REMOTE_ADDR` fallback; plus introspection pinning the three controllers to the settings-driven stacked profile
- [x] 3.2 Base-controller error mapping: `TooManyRequestsError` → `ErrorCode.throttled` (distinct from `validation_error`); feedback tests stay green on the new key/backend (75 passed across availability + feedbacks + api)
- [x] 3.3 Contract surface: `SAFE_OPERATIONS` in `tests/contract/test_schemathesis.py` contains no availability endpoints — no change needed

## 4. Contract & docs

- [x] 4.1 API snapshot regenerated (3 × documented 429 on the availability endpoints; prettier-normalized at commit); `python3 -m server.apps.apiversions.registry_check` passes with no new version — additive change per design D5
- [x] 4.2 Ops note in the PR body: `app createcachetable` deploy step; nginx `proxy_set_header X-Forwarded-For $remote_addr` (overwrite, not append)
