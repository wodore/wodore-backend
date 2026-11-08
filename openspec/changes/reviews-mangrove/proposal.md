# Proposal: reviews-mangrove

## Why

Wodore lists 1585 public huts but has no reviews — and nobody else does either:
the Mangrove open review dataset (14 504 reviews as of the 2026-11-08 dump)
holds zero alpine-hut reviews. Integrating [Mangrove
Reviews](https://docs.mangrove.reviews) (Open Reviews Association, ORA) gives
Wodore hut ratings, opinions and photos without building a review backend,
publishes every review as open data (CC-BY-4.0, matching our OSM-based
sourcing ethos), and positions Wodore as the first mover for alpine huts in a
system that MapComplete, mangrove.reviews and Swiss tourism partners already
use.

## What Changes

- **New Django app `server/apps/reviews`** that proxies the Mangrove API
  (0.4.1) for reading *and* writing — anonymous visitors read, Wodore
  accounts write. No review content is owned solely by Wodore: the upstream
  dataset is the source of truth, Wodore relays, caches and moderates.
- **Deterministic subject URI recipe**: every hut's Mangrove subject is
  `geo:<lat>,<lon>?q=<hut-slug>&u=<radius>` — coordinates from
  `Hut.location`, `q` is the **Wodore slug** (byte-stable, unique,
  multilingual-proof; uniqueness verified under upstream's normalized
  matching), deliberately forgoing name matching with other clients
  (existing hut review stock ≈ 0, so nothing to match against).
- **Server-held reviewer identity**: one ES256 (P-256) Mangrove keypair per
  user account, encrypted at rest; the backend signs and submits all review
  JWTs via `POST /submit` (the standard explicitly supports "a review
  submitting service which manages user keys"). This enables user-initiated
  edit/delete/report-abuse (all require the original key), a v1 GDPR erasure
  command, and per-user quota. Opt-in JWK import/export (bring your
  MapComplete identity) is a later phase; OSM-preference sync and `did:web`
  identity are future notes only.
- **API (additive, no `Api-Version` bump, one operation per path)**:
  `GET /v1/huts/{slug}/reviews` (public, cacheable) and its
  `…/reviews/summary`, `GET /v1/reviews/summary?slugs=…` for map-badge
  batches, `POST /v1/huts/{slug}/reviews/submit` (auth + quota +
  validation, relays), `POST …/reviews/{signature}/edit|delete|report`,
  `GET /v1/my/reviews`. Standard dmr conventions, error contract and
  Api-Version middleware apply automatically.
- **Moderation**: OIDC auth gate on writes, per-user submission quota,
  server-side signature blacklist (hidden from our listings), abuse reports
  relayed as signed `report_abuse` actions.
- **OSM metadata from the existing linkage**: review submissions stamp
  `metadata.osm_id` (`node/ID` / `way/ID` form) from the hut's existing
  `HutSource` linkage (org `osm`, fed by the hut import pipeline) — no new
  matching job; gap-filling and refresh stay with the import pipeline.
- **Review images** in scope: `images` (`{src, label}` × ≤5) validated and
  relayed — the upstream server fetches and persists them (dump-verified:
  they land on `files.mangrove.reviews`, which is the serving allowlist).
- **Resilience & contract pinning**: an `httpx`-based `MangroveClient`
  (timeouts, GET-only retries, structlog + Sentry tracing) whose payload
  expectations are pinned to upstream 0.4.1 with recorded fixtures captured
  against reserved test subjects.
- **Frontend work is explicitly out of scope** (informative tasks listed
  for the Quasar app, later).

## Capabilities

### New Capabilities

- `hut-reviews`: public review read API and authenticated write API on huts
  (list, summary/batch aggregates, submit, edit/delete/report, my-reviews),
  moderation gates (auth, quota, signature blacklist), caching behavior.
- `mangrove-client`: the upstream integration service — subject URI recipe,
  httpx client with timeouts/retries/observability, 0.4.1 contract pinning,
  signed write relay, local submission log (data sovereignty/GDPR).
- `review-identity`: per-account Mangrove keypairs — encrypted server-side
  custody, lazy minting, signing service, ownership enforcement, erasure
  path (import/export is a later phase, not in this change's spec).

### Modified Capabilities

(none — the change is purely additive: new app, new endpoints, no new jobs.
Hut endpoints and their ETags are untouched; review volatility stays on
separate endpoints.)

## Impact

- **Code**: new app `server/apps/reviews` (models: reviewer key, reviewer
  profile, submission log, blacklist; dmr controllers; `MangroveClient`
  service; erasure management command), a settings component (`MANGROVE_*`
  env via Infisical: base URL, timeout, key-encryption key, quota defaults,
  image-host allowlist), Unfold admin + tab, router wiring in `api_v1.py`.
- **API**: new `/v1/` endpoints (additive — no version bump, no committed
  snapshot), one new registered error code (`review_quota_exceeded`); all
  other errors reuse the existing registry (`validation_error`,
  `service_unavailable`, `not_authenticated`, `insufficient_permission`,
  `not_found`). Short public cache TTLs on reads; no CDN purge integration.
- **Dependencies**: `httpx` + `cryptography` (both already in tree),
  `respx` (dev-only, for mocked-client tests),
  `https://api.mangrove.reviews` (external, 0.4.1, not frozen → pinned via
  fixtures).
- **Privacy/legal**: server-held private keys are encrypted at rest and never
  served publicly in v1 (export is phase 2); reviews are published under
  Mangrove ToS with CC-BY-4.0 (attribution surfaced in API payloads); GDPR
  erasure ships in v1 (signed `delete` actions + local record destruction;
  PROTECT foreign keys make silent key loss on account deletion
  impossible).
- **Frontend** (separate repo, later): hut-page review list/submit UI, star ↔
  rating mapping, my-reviews profile section, map badges.
- **Docs**: AGENTS.md gains a reviews section.
