## Why

The public `/v1/` API serves heavy, real-cost data (PostGIS geometry queries,
hut/booking reads that fan out to external hut-services upstreams) and a
public write endpoint (`POST /v1/feedback/`) with no caller verification at
all — anyone with `curl` can scrape or abuse them. We need to verify that a
request comes from one of our frontends (web SPA today, the Android app
later) without requiring user authentication.

A public web frontend cannot hold a secret (the bundle is downloadable), so
true cryptographic verification is impossible for the web client. The
pragmatic industry pattern (publishable keys à la Mapbox/Stripe) is layered
deterrence: server-side origin allowlisting plus per-client API keys that
are rate-limited, observable, and instantly revocable.

## What Changes

- New **client key registry**: an `ApiClient` model (hashed key, name,
  platform tag, `is_active`, per-key rate limit, `last_used_at`, request
  counters) with issuance/rotation via a management command and full CRUD in
  the Unfold admin.
- New **layered gate** on the abuse-prone public surface —
  `/v1/huts/*`, `/v1/geo/*` (incl. `/geo/images/`), `POST /v1/feedback/`:
  - `X-Client-Key` header must reference an active key (constant-time hash
    lookup);
  - if an `Origin`/`Referer` header is present it must match the trusted
    frontend origins (derived from `DJANGO_TRUSTED_DOMAINS`), regardless of
    key validity — a leaked key cannot be re-hosted in another website.
- **Per-key fixed-window rate limiting** (cache-backed counter, generous
  budgets, `429` on breach) — protects the external fan-out paths from
  hammering even with a valid key.
- **Kill-switch**: `CLIENT_VERIFY_ENABLED` env flag — enforcing on by
  default in production/staging, off in development/test so local work and
  CI need no keys; flipping it off restores today's fully open behavior.
- Static, cacheable, high-volume asset endpoints (`/v1/symbols/*`,
  `/v1/categories/*`, `/v1/meteo/*`, `/v1/version`) stay **ungated** — a DB
  or cache hit per tiny SVG fetch adds cost without abuse value.
- **BREAKING**: the currently unauthenticated mutations — organizations
  `POST/PUT/DELETE`, symbols `POST` — now require a valid bearer token
  (existing `AuthBearer`). The SPA already sends tokens for these flows;
  any unknown external consumers lose anonymous write access (that is the
  point).
- No changes to user-facing auth (allauth/OIDC) or the token-validation
  specs beyond the mutation gating above.

## Capabilities

### New Capabilities

- `public-api-client-gating`: enforcement contract for gated public
  endpoints — key validation, origin allowlist, rate limiting, kill-switch
  semantics, error responses (`403`/`429` shapes), the gated path scope,
  and bearer-auth on the public write endpoints.
- `api-client-keys`: lifecycle of client keys — issuance, rotation,
  revocation, storage as hashes only, platform tagging, and admin/command
  management surfaces.

### Modified Capabilities

<!-- None: no existing spec's requirements change. api-token-validation
     gains no new requirements (AuthBearer reuse is implementation), and no
     existing spec covers the organizations/symbols endpoints. -->

## Impact

- **Backend code**: `server/apps/api/` (gate dependency/middleware, gate
  wiring in `api_v1.py` mounts), new models + migration (key registry —
  likely inside `server.apps.api` or a small dedicated app), settings
  component (`CLIENT_VERIFY_ENABLED`, rate-limit defaults, origin list
  derivation), Unfold admin registration + TABS, management command
  (`client_keys create/rotate/list`), Swagger docs note for header testing.
- **Frontend (wodore-frontend-quasar)**: ships `X-Client-Key` on all gated
  calls (one axios/fetch interceptor) — coordinated release: staging key
  first, then production key at rollout; existing bearer tokens already
  cover the newly authed mutations.
- **Operations**: one staging + one production web key issued via Infisical;
  future Android key issued from the same registry; kill-switch runbook
  line (`CLIENT_VERIFY_ENABLED=false`).
- **Testing**: gate behavior (valid/missing/revoked key, foreign origin,
  rate-limit breach, kill-switch on/off), mutation auth (401 without/with
  token), key lifecycle command/admin coverage.
