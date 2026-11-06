## 1. Foundation

- [ ] 1.1 Scaffold `server.apps.api_clients` app (apps.py, `__init__.py`), register in INSTALLED_APPS, add Unfold TABS entry
- [ ] 1.2 `ApiClient` model (name, platform, key_hash unique+indexed, is_active, rate_limit nullable, last_used_at, request_count, TimeStampedModel) + migration
- [ ] 1.3 Settings component: `CLIENT_VERIFY_ENABLED` (default on in production/staging, off in development/test), `CLIENT_RATE_LIMIT_DEFAULT`, trusted-origins derivation from `DJANGO_TRUSTED_DOMAINS`, gated-prefixes constant
- [ ] 1.4 Key generation helper (`wod-<platform>-<urlsafe>`, SHA-256 hashing) with unit tests

## 2. Gate middleware

- [ ] 2.1 Middleware: path-prefix match, `OPTIONS` bypass, kill-switch short-circuit; install after CorsMiddleware
- [ ] 2.2 Key validation: header → hash → registry lookup (process-local LRU with ~60 s TTL); missing/unknown/inactive → uniform `403`
- [ ] 2.3 Origin/Referer layer: when present, host must be in trusted origins, else `403` regardless of key
- [ ] 2.4 Fixed-window rate limit via Django cache (`incr`+ttl), per-key budget (model override, settings default), `429` + `Retry-After`; fail-open on cache errors with loud log
- [ ] 2.5 Throttled telemetry update (last_used_at, request_count) — no per-request DB writes
- [ ] 2.6 Error responses match the API error shape (`403`/`429` JSON)

## 3. Mutation authentication

- [ ] 3.1 Add `auth=AuthBearer()` to organizations POST/PUT/DELETE and symbols POST operations
- [ ] 3.2 Audit api_v1 routers for any other unauthenticated mutations

## 4. Operations

- [ ] 4.1 Management command `client_keys` (create/rotate/deactivate/list; full key printed exactly once)
- [ ] 4.2 Unfold admin registration: CRUD, active toggle, truncated hash display, no key material on forms
- [ ] 4.3 Purge local LRU entry on admin deactivation/rotation

## 5. Tests

- [ ] 5.1 Gate scenarios per spec: valid/missing/revoked key, trusted/foreign/absent origin, OPTIONS preflight bypass, ungated endpoints open
- [ ] 5.2 Rate limit: budget exhaustion → 429 + Retry-After; window reset
- [ ] 5.3 Kill-switch off: gated endpoints fully public, no key/origin/rate-limit interaction
- [ ] 5.4 Mutation auth: anonymous → 401; valid token → succeeds
- [ ] 5.5 Key lifecycle: create/rotate/deactivate via command and admin; hash-only storage
- [ ] 5.6 Full suite green (`scripts/lane-run.sh .venv/bin/pytest` in worktree)

## 6. Rollout & docs

- [ ] 6.1 Update deploy prompt/runbook: rollout ordering (D9), Infisical entries `web-staging`/`web-prod`, kill-switch line
- [ ] 6.2 Swagger/API docs note: how to test gated endpoints with a header
- [ ] 6.3 Coordinate frontend PR (X-Client-Key interceptor) — wodore-frontend-quasar
- [ ] 6.4 Archive the change via openspec when implemented
