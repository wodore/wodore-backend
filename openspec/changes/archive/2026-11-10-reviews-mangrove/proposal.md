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

- **New Django app `server/apps/reviews`** that proxies the Open Reviews API
  (0.4.1) for reading *and* writing — anonymous visitors read, Wodore accounts
  write. No review content is owned solely by Wodore: the upstream dataset is
  the source of truth, Wodore relays, caches, filters and moderates.
- **Subject URI recipe with review names**: `geo:<lat>,<lon>?q=<review-name>&u=<radius>`
  — the review name resolves as **OSM name → hut name** and is **pinned on
  the hut's first review** (`HutReviewSubject`) so renames never fork the
  subject. OSM-name `q`s make Wodore subjects cross-client matchable with
  MapComplete. The `q` encoding is verified live (`+`-spaces at submit,
  percent-encoded accents, both match).
- **Server-held reviewer identity**: one ES256 (P-256) Mangrove keypair per
  user account, encrypted at rest; the backend signs and submits all review
  JWTs via `POST /submit` (the standard explicitly supports "a review
  submitting service which manages user keys"). This enables user-initiated
  edit/delete/report-abuse (all require the original key), a v1 GDPR erasure
  command, and per-user quota. Keys are minted only on actual writes (not
  on doomed 403/404 requests). Opt-in JWK import/export (bring your
  MapComplete identity) is a later phase.
- **API (additive, no `Api-Version` bump, one operation per path)**:
  - `GET /v1/huts/{slug}/reviews` — public, CDN-cacheable, merged listing
  - `GET /v1/huts/{slug}/reviews/summary` — locally computed aggregate
  - `GET /v1/reviews/summary?slugs=…` — batch aggregates for map badges
  - `POST /v1/huts/{slug}/reviews/submit` — auth + quota, signs + relays
  - `POST …/{signature}/edit|delete|report` — signed MaReSt actions
  - `POST …/{signature}/reply` — signed reply (`urn:maresi` subject), accepts images
  - `GET …/{signature}/replies` — per-review replies (cached per signature)
  - `POST /v1/huts/{slug}/reviews/merge-request` — staff queue for merges
  - `POST /v1/reviews/images` — **photo upload relay** to Mangrove's open
    upload server (`upload.mangrove.reviews`, ≤5 photos, ≤4.5 MB) —
    Wodore stores nothing; returns `files.mangrove.reviews/<hash>` URLs
  - `GET /v1/my/reviews` — caller's reviews with hut annotation
- **Read-only provider merge**: hut listings merge refuges.info community
  comments (CC BY-SA 2.0 FR, verified live: 19–54 comments per sampled
  refuge) with per-review `source`/`license`/`link` attribution — never
  re-published into Mangrove. Provider failures degrade to Mangrove-only;
  refuges back-pressure (2.5 s timeout, 60 s negative cache, batch uses
  cached-only data).
- **OpenReviewsProvider (image gallery)**: hut review photos served through
  the standard image-provider pipeline (imagor variants, CC-BY-4.0
  license rows, reviewer-nickname attribution). After a submit with
  images, the provider cache for the hut's coordinates is invalidated
  (otherwise 24 h TTL delays new photos).
- **Visibility overlay**: every list build overlays the subject's recent
  accepted submission-log rows — own submits prepended, deleted targets
  dropped, edited targets patched — regardless of cache state or worker.
  All review caches on the **shared DB cache alias** (cross-process;
  LocMem is per-worker). Edit rows from upstream (which carry their own
  signature + `original_sub`) are kept with stable original-signature
  identity, both-signature blacklist, and geo-match on `original_sub`.
- **Moderation**: OIDC auth gate on writes, per-user submission quota
  (5 submit/day, 20 edit+delete/day), server-side signature blacklist
  (admin delete, covers both Mangrove and provider ids, tracks edits),
  abuse reports relayed as signed `report_abuse` actions, staff queue for
  user-filed merge requests.
- **Upstream resilience**: all upstream failures map to sanitized 503
  (never 500); GET-only bounded retries; httpx timeouts; contract
  pinned to 0.4.1 via recorded fixtures (reserved test subjects only);
  edit-row shape, `q` encoding and photo upload verified live.
- **Image strictness**: `images[].src` checked for parser-confusion
  bypasses (`\@`, ports, control chars) before the allowlist check.
- **Write guard**: `ORA_WRITES_ENABLED` (default off) gates all write
  paths — no Open Reviews sandbox exists.

  **Kill-switch matrix**: `ORA_ENABLED` gates Mangrove reads+writes;
  `ORA_REFUGES_INFO_ENABLED` independently gates the provider
  (both off = full read-dark; enabled-but-keyless in production fails
  startup). Settings default: on in dev/test, off in production.
- **Frontend work is explicitly out of scope** (informative tasks listed
  for the Quasar app, later).

## Capabilities

### New Capabilities

- `hut-reviews`: public review read API and authenticated write API on huts
  (list with provider merge, summary/batch aggregates, submit,
  edit/delete/report/reply/replies, merge requests, photo upload relay,
  my-reviews), moderation gates (auth, quota, signature blacklist),
  own-write overlay visibility, caching behavior.
- `mangrove-client`: the upstream integration service — subject URI recipe
  (review names, pinning, verified `q` encoding), httpx client with
  timeouts/retries/observability, 0.4.1 contract pinning (incl. edit-row
  fixture), signed write relay (submit + photo upload), local submission
  log (data sovereignty/GDPR), shared-cache alias for cross-process
  visibility.
- `review-identity`: per-account Mangrove keypairs — encrypted server-side
  custody, lazy minting (only on actual writes), signing service, ownership
  enforcement, erasure path. JWK import/export is a later phase.

### Modified Capabilities

(none — the change is purely additive: new app, new endpoints, no new jobs.
Hut endpoints and their ETags are untouched; review volatility stays on
separate endpoints.)

## Impact

- **Code**: new app `server/apps/reviews` (models: reviewer key, reviewer
  profile, hut review subject, submission log, merge request, blacklist;
  dmr controllers incl. photo upload; `OpenReviewsClient` with photo upload;
  `RefugesInfoClient` read-only provider; `OpenReviewsProvider` image gallery
  provider; erasure management command), a settings component (`ORA_*`
  env via Infisical: base URL, timeout, key-encryption key, quota defaults,
  image-host allowlist, refuges back-pressure, kill-switches), Unfold
  admin + tab, router wiring in `api_v1.py`, `OpenReviewsProvider` registered
  in `geometries/providers/__init__.py`.
- **API**: new `/v1/` endpoints (additive — no version bump, no committed
  snapshot), one new registered error code (`review_quota_exceeded`); all
  other errors reuse the existing registry. Short public cache TTLs on
  reads; no CDN purge integration.
- **Dependencies**: `httpx` + `cryptography` (both already in tree),
  `respx` (dev-only), `https://api.mangrove.reviews` (0.4.1, not frozen →
  pinned via fixtures incl. edit-row shape), `https://upload.mangrove.reviews`
  (photo upload, verified live), `https://www.refuges.info/api/` (comments,
  verified live, CC BY-SA 2.0 FR).
- **Privacy/legal**: server-held private keys encrypted at rest, never
  served; reviews published under Mangrove ToS with CC-BY-4.0 (per-review
  `license` field; attribution in API payloads); refuges.info comments
  served with CC-BY-SA 2.0 FR per-review attribution; GDPR erasure in v1;
  PROTECT FKs make silent key loss on account deletion impossible.
- **Frontend** (separate repo, later): hut-page review list/submit UI, star ↔
  rating mapping, my-reviews profile section, map badges, photo upload flow.
- **Docs**: AGENTS.md § Reviews; specs/design/tasks in this change.
