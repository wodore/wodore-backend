# Design: verify-public-api-clients

## Context

The public `/v1/` API (Django Ninja, mounted in `server/apps/api/api_v1.py`)
serves expensive data — PostGIS geometry queries under `/v1/geo/*`, hut and
booking reads under `/v1/huts/*` that fan out to external hut-services
upstreams — plus a public write (`POST /v1/feedback/`), all with zero caller
verification. User auth (allauth/OIDC tokens via `AuthBearer`) exists but is
separate: these endpoints are deliberately usable without login. The web SPA
(wodore-frontend-quasar) is the client today; an Android app is planned.

Hard constraint: a public web frontend cannot hold a secret — anything in
the bundle is extractable. So "verify the frontend" means layered
deterrence, not proof: origin allowlisting (browsers cannot fake `Origin`)
plus publishable-style client keys that are rate-limited, observable, and
revocable. See proposal for the endpoint tiering (heavy reads + feedback
gated; static assets stay open).

Relevant existing pieces: `DJANGO_TRUSTED_DOMAINS` (comma-separated env →
`server/settings/components/common.py`) already lists the trusted frontend
origins; `CACHES` is configured (`components/caches.py`); corsheaders
middleware is in place; `server.apps.api` is a plain package, **not** an
installed app (no models there today).

## Goals / Non-Goals

**Goals**

- Gated endpoints (`/v1/huts/*`, `/v1/geo/*`, `POST /v1/feedback/`)
  require an active client key; foreign browser origins rejected even with
  a valid key.
- Per-key rate budgets; instant revocation; usage telemetry.
- Runtime kill-switch (`CLIENT_VERIFY_ENABLED`) restoring today's open
  behavior.
- Token-auth the accidentally-public mutations (organizations
  POST/PUT/DELETE, symbols POST).
- Web and (future) Android each get their own key from the same registry.

**Non-Goals**

- True web-client attestation (impossible for public bundles).
- Play Integrity / app attestation for Android (revisit when the app
  exists and abuse appears — the key header gives the hook for it).
- Gating static asset endpoints (symbols/categories/meteo/version).
- Per-user rate limiting, IP bans, bot detection.

## Decisions

**D1 — Gate as Django middleware, not Ninja router wiring.**
A single middleware matches the gated path prefixes (`/v1/huts`, `/v1/geo`,
`/v1/feedback`), installed directly after `CorsMiddleware`. Alternatives
rejected: per-router `auth=`/dependency wiring in Ninja — conflates client
identity with user auth semantics, must be remembered for every future
router, and the feedback mount (POST-only) is prefix-shaped anyway (its
only route is POST). Middleware also gives one place for the kill-switch
and an automatic `OPTIONS` bypass (preflights must never be gated).
Trade-off: path prefixes live outside the API layer — mitigated by a
tests-pinned constant and the spec's ungated-endpoints requirement.

**D2 — Keys in a new small app `server.apps.api_clients`.**
`server.apps.api` is not an installed app; rather than retrofit it into
INSTALLED_APPS with migrations, a dedicated app keeps the registry isolated
(auth apps already follow this pattern in the project). Model
`ApiClient`: `name`, `platform` (tag: web/android/…), `key_hash` (SHA-256
hex, unique, indexed), `is_active`, `rate_limit` (nullable per-key budget),
`last_used_at`, `request_count`, TimeStampedModel per project convention.

**D3 — Key format and validation.**
Keys: `wod-<platform>-<43 chars urlsafe random>` (recognizable in logs,
platform-greppable). Validation is hash-then-lookup: SHA-256 the presented
header and query `key_hash` (one indexed row); lookup miss = same `403` as
revoked. Hash-then-index means no timing side channel worth attacking and
no plaintext anywhere. A tiny process-local LRU (hash → row, ~60 s TTL)
keeps hot paths off the DB; revocation latency ≤ TTL, acceptable (spec:
next-request semantics, bounded staleness for telemetry; revocation within
60 s documented as the worst case — deactivate also purges the local cache
on the admin node; other nodes converge within TTL).

**D4 — Origin layer derived from `DJANGO_TRUSTED_DOMAINS`.**
When `Origin` or `Referer` is present, its host must be in the trusted set
(already env-driven, already lists the frontend domains). Absent headers
(native apps, server-side tools) pass this layer — the key is their
verification. This blocks re-hosting an extracted key in another website.

**D5 — Rate limiting: fixed window in the Django cache.**
Counter key `clientrl:<key_hash>:<epoch-window>` via cache
`incr`+`ttl`; `429` with `Retry-After` on breach. Default budget from
settings (`CLIENT_RATE_LIMIT_DEFAULT`, generous — e.g. 600/min), per-key
override via the model column. Cache unavailable → fail-open on the
rate-limit layer only (loud log); key validation itself is DB-backed and
unaffected.

**D6 — Kill-switch semantics.**
`CLIENT_VERIFY_ENABLED`: default **True in production/staging, False in
development/test** (local dev, Swagger docs and CI need no keys). Off →
middleware short-circuits before any DB/cache work: today's behavior
byte-for-byte.

**D7 — Mutation auth via existing `AuthBearer`.**
Organizations POST/PUT/DELETE and symbols POST gain `auth=AuthBearer()` on
their Ninja operations. The SPA already sends tokens for these flows; the
token-validation validators are unchanged.

**D8 — Operations surface.**
Management command `client_keys` with `create/rotate/deactivate/list`
subcommands (prints the full key exactly once at create/rotate). Unfold
admin CRUD + TABS entry; key hash shown truncated, never a full key, no
key field on edit.

**D9 — Rollout ordering (the deployment-critical piece).**
Backend must not enforce in production before the SPA ships the header.
Sequence: (1) deploy backend with `CLIENT_VERIFY_ENABLED=false` explicitly
set in prod (code default on, env overrides off) — mutations token-auth
goes live (SPA ready); (2) frontend release adds `X-Client-Key` from new
Infisical entries (`web-staging`, `web-prod` keys); (3) verify on staging
(enforcing there since before the frontend change), then remove the prod
override — enforcing. Kill-switch line goes in the runbook/deploy prompt.

## Risks / Trade-offs

- [Key extracted from the SPA bundle] → per-key budgets cap damage;
  rotation and revocation are instant-ish (≤60 s cache convergence); origin
  layer blocks browser re-hosting; budgets tunable per key.
- [Legit consumer breaks at enforcement flip] → kill-switch env restores
  open behavior in seconds, no deploy; staging rehearsal before prod.
- [Per-request overhead] → hash lookup on a unique index (+ LRU) is one
  cheap query; rate-limit is one cache op; telemetry writes are throttled,
  never per-request.
- [Revocation latency via LRU] → bounded at TTL (~60 s); acceptable for
  scraping response, documented.
- [Unknown consumers of public mutations break] → intended; SPA unaffected;
  changelog note in the release.
- [Scope coupling of paths in middleware] → prefixes pinned by tests;
  ungated endpoints covered by spec scenario.

## Migration Plan

1. Merge/deploy backend with prod `CLIENT_VERIFY_ENABLED=false` (migration
   creates the `api_clients` tables; no data migration).
2. Issue `web-staging` key (command), set in Infisical; staging gate is
   enforcing by default — verify SPA staging build with header.
3. Frontend PR: attach `X-Client-Key` (env-driven) to gated call sites (one
   interceptor); release to staging, then prod.
4. Issue `web-prod` key, set in Infisical, remove the prod
   `CLIENT_VERIFY_ENABLED=false` override → enforcing.
5. Rollback at any step: set `CLIENT_VERIFY_ENABLED=false` (no deploy).

## Open Questions

- Telemetry write strategy exact batching (per-process flush interval vs
  cache-aggregated counters) — decide during implementation; spec only
  demands bounded staleness.
- Whether feedback POST additionally wants spam hardening (honeypot/MTA
  checks) — separate concern, not this change.
