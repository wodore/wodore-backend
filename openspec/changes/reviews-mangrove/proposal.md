# Proposal: reviews-mangrove

## Why

Wodore lists 1585 public huts but has no reviews — and nobody else does either:
the Mangrove open review dataset holds ~728 reviews in the Alps bbox, all on
Swiss tourism-portal geo subjects, with effectively **zero alpine-hut
reviews**. Integrating [Mangrove Reviews](https://docs.mangrove.reviews) (Open
Reviews Association, ORA) gives Wodore hut ratings, opinions and photos without
building a review backend, publishes every review as open data (CC-BY-4.0,
matching our OSM-based sourcing ethos), and positions Wodore as the first mover
for alpine huts in a system that MapComplete, mangrove.reviews and Swiss
tourism partners already use.

## What Changes

- **New Django app `server/apps/reviews`** that proxies the Mangrove API
  (0.2.0) for reading *and* writing — anonymous visitors read, Wodore accounts
  write. No review content is owned solely by Wodore: the upstream dataset is
  the source of truth, Wodore relays, caches and moderates.
- **Deterministic subject URI recipe**: every hut's Mangrove subject is
  `geo:<lat>,<lon>?q=<hut-slug>&u=<radius>` — coordinates from
  `Hut.location`, `q` is the **Wodore slug** (byte-stable, unique,
  multilingual-proof), deliberately forgoing fuzzy name matching with other
  clients (existing hut review stock ≈ 0, so nothing to match against).
- **Server-held reviewer identity**: one ES256 (P-256) Mangrove keypair per
  user account, encrypted at rest; the backend signs and submits all review
  JWTs (the standard explicitly supports "a review submitting service which
  manages user keys"). This enables user-initiated edit/delete/report-abuse
  (all require the original key), GDPR erasure, and per-user quota.
  Opt-in JWK import/export (bring your MapComplete/mangrove.reviews identity)
  is a later phase; OSM-preference sync and `did:web` identity are future
  notes only.
- **API (additive, no `Api-Version` bump)**: `GET /v1/huts/{slug}/reviews`
  (public, CDN-cacheable), `GET /v1/huts/{slug}/reviews/summary` plus a
  multi-hut batch summary for map badges, `POST /v1/huts/{slug}/reviews`
  (auth + quota + validation, relays), edit/delete/report endpoints,
  `GET /v1/me/reviews`. Standard dmr conventions, error contract and
  Api-Version middleware apply automatically.
- **Moderation**: OIDC auth gate on writes, per-user submission quota,
  server-side signature blacklist (hidden from our listings), abuse reports
  relayed as signed `report_abuse` actions.
- **OSM linkage batch job** (django-q2, Overpass API): recurring job that
  links/refreshes huts ↔ OSM elements — filling the 27% unlinked gap and
  verifying the 1166 existing links — feeding the standard
  `metadata.osm_id` claim on submitted reviews. No permission needed
  (ODbL); ambiguous matches go to an admin review queue.
- **Review images** in scope: `images` (`{src, label}` × ≤5) validated and
  relayed; the upstream server fetches and persists them (hosting nuance is
  an open decision).
- **Resilience & contract pinning**: an `httpx`-based `MangroveClient`
  (timeouts, bounded retries, structlog + Sentry tracing) whose payload
  expectations are pinned to upstream 0.2.0 with recorded fixtures.
- **WEP011** board post summarizing the change; **frontend work is explicitly
  out of scope** (informative tasks listed for the Quasar app, later).

## Capabilities

### New Capabilities

- `hut-reviews`: public review read API and authenticated write API on huts
  (list, summary/batch aggregates, submit, edit/delete/report, my-reviews),
  moderation gates (auth, quota, signature blacklist), caching/CDN behavior.
- `mangrove-client`: the upstream integration service — subject URI recipe,
  httpx client with timeouts/retries/observability, 0.2.0 contract pinning,
  signed write relay, local submission log (data sovereignty/GDPR).
- `review-identity`: per-account Mangrove keypairs — encrypted server-side
  custody, lazy minting, signing service, ownership enforcement, JWK
  import/export (later phase), erasure path.
- `hut-osm-linkage`: recurring Overpass-based job linking huts to OSM
  elements with an ambiguity review queue, feeding review metadata.

### Modified Capabilities

(none — the change is purely additive: new app, new endpoints, new jobs. Hut
endpoints and their ETags are untouched; review volatility stays on separate
endpoints.)

## Impact

- **Code**: new app `server/apps/reviews` (models: reviewer key, submission
  log, blacklist, OSM link candidates; dmr controllers; `MangroveClient`
  service; management commands for the OSM job and user erasure), a settings
  component (`MANGROVE_*` env via Infisical: base URL, timeout, key-encryption
  key, quota defaults), Unfold admin + tab, django-q2 schedule entries.
- **API**: new `/v1/` endpoints (additive — no version bump, no snapshot
  transforms), new error codes in the RFC 9457 registry
  (`upstream_unavailable`, review validation/quota codes), CDN-Tag
  `api:reviews` with write-through purge.
- **Dependencies**: `httpx` (client), `cryptography`/authlib (ES256 + JWK —
  already in tree via OIDC), Overpass API (external, ODbL),
  `https://api.mangrove.reviews` (external, 0.2.0, not frozen → pinned via
  fixtures).
- **Privacy/legal**: server-held private keys are encrypted at rest and never
  served publicly (export only to the owning account); reviews are published
  under Mangrove ToS with CC-BY-4.0 (attribution surfaced in API payloads);
  GDPR erasure = signed `delete` actions + local record destruction.
- **Frontend** (separate repo, later): hut-page review list/submit UI, star ↔
  rating mapping, my-reviews profile section, map badges.
- **Docs**: WEP011 board post; AGENTS.md gains a reviews section.
