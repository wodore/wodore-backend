# Design: reviews-mangrove

## Context

**Mangrove Reviews** (Open Reviews Association, ORA) is a decentralized review
system: a review is an ES256-signed JWT (Mangrove Review Standard, MaReSt
v0.7.0) stored on the Original Mangrove Server at `https://api.mangrove.reviews`
(OpenAPI 0.2.0 — live, CORS-open, *not frozen*). The dataset is open data
(CC-BY-4.0 by default per the Terms of Service). Existing consumers:
MapComplete (stores the reviewer's private JWK in OSM user preferences), the
mangrove.reviews web app (localStorage), and Swiss tourism portals whose
~728 Alpine reviews are the entire regional stock — all `geo:` subjects, and
effectively none on alpine huts. Wodore would be the first mover for huts.

Relevant Mangrove mechanics (verified against the standard and live API):

- **Subject** (`sub` claim): core URI schemes `https` (server HEAD-checks
  public host on submit), `geo:lat,lon?q=…&u=…` (RFC 5870 with query-string
  parameters; `q` required ≤100 chars, `u` = uncertainty radius in meters,
  0 < u ≤ 10000), `urn:isbn`, `urn:lei`, `urn:maresi` (references another
  review by signature), `did:` (identity actions only). There is **no**
  `urn:osm` scheme.
- **geo matching is exact-`q` + radius-sum**: two geo subjects match iff
  their `q` strings are identical AND their coordinates are within the *sum*
  of both `u` values. No fuzzy name matching anywhere in matching (live-
  verified: same `q` + 8 m coordinate perturbation still matches; different
  `q` at identical coordinates returns nothing).
- **Actions**: besides rating/opinion reviews, a JWT with an `action` claim
  performs `edit` / `delete` / `report_abuse` (all `sub` =
  `urn:maresi:<signature of the target review>`; edit/delete MUST be signed
  by the original key, report_abuse by any key and MUST NOT carry a rating),
  `equivalence` (asserts two subject URIs denote the same entity; resolved
  server-side by union-find weighted by issuer credibility — a fresh key
  weighs 0), and `identity`/`profile` (`did:web`/`did:plc` — **in the
  standard and server master but not live on api.mangrove.reviews**; design
  for, never depend on).
- **Review payload**: `rating` 0–100 (likelihood to recommend), `opinion`
  ≤1000 chars, at least one of rating/opinion/action required; `images`
  ≤5 items of `{src: URL, label?: ≤50 chars}` — the upstream server fetches
  and persists images server-side; `metadata` object with core keys
  (`nickname`, `client_id`, `language` BCP 47, `experience_context`,
  `is_personal_experience`, `is_affiliated`, `license` SPDX
  {`CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-SA-3.0`}, `osm_id` in
  `node/ID[/VERSION]` form, …). Header carries the public key twice
  (`kid` PEM + `jwk` JSON-string).
- **API surface (live, 0.2.0)**: `GET /reviews?sub=&kid=&q=&limit=`,
  `GET /geo?xmin&ymin&xmax&ymax`, `GET /subject/{sub}` (aggregates: count,
  quality, positive_count…), `GET /issuer/{pem}` (count, credibility 0–1),
  `GET /review/{signature}`, `POST /batch` (aggregates for multiple subs —
  exact subjects only), `PUT /submit/{jwt}`.
- **Identity is the keypair**: `kid` = PEM public key; all reviews of one
  identity via `GET /reviews?kid=`. No OAuth anywhere upstream. The standard
  explicitly blesses "a review submitting service which manages user keys in
  a centralized fashion, allowing for easy integration with existing login
  infrastructure" — exactly the Wodore model below.

**Wodore facts** (verified in-repo): `Hut` (`server/apps/huts/models/_hut.py`)
has a unique `slug`, PostGIS `location` Point (WGS84), multilingual names
(modeltrans, `main_language`); 1585 public+active huts in dev. `HutSource`
rows with organization slug `osm` already link 1166/1585 huts (73%; 480 node,
926 way) — `source_id` = bare numeric OSM id, `source_data` JSON with
`osm_type`, `tags`, `center_lat/lon`. django-q2 is the batch-job precedent
(e.g. availability sync); dmr controllers serve `/v1/` with the shared error
contract (RFC 9457 members), `Api-Version` middleware, and the CDN-Tag
taxonomy `api api:<app>`; `AuthBearer` (`server/apps/api/auth.py`) validates
OIDC (Zitadel) or local-dev tokens; the custom `User` (`accounts`) is
email-identity with UUID pk.

Everything below was decided with the owner during planning; genuinely
unresolved details are collected under **Open decisions** with a
recommendation each — implementation PRs resolve them there.

## Goals / Non-Goals

**Goals:**

- Hut reviews readable by anonymous clients and writable by Wodore accounts,
  with all Mangrove traffic proxied through the backend (no client-side
  upstream calls, no upstream key material in browsers).
- A **deterministic, stable subject URI per hut** so reviews survive
  renames, translations and portal churn, and so future equivalence claims
  can bridge Wodore subjects to OSM-name subjects.
- Server-side key custody that makes edit/delete/report/GDPR-erasure
  possible for logged-in non-crypto users, with encrypted-at-rest private
  keys and an append-only local record of what we submitted.
- Upstream-resilient reads (caching + timeouts + graceful degradation) and
  a **pinned contract** so upstream 0.2.x drift fails our tests, not
  production requests.
- OSM linkage good enough to stamp `metadata.osm_id` on hut reviews and to
  power later cross-client bridging.
- An additive API (no `Api-Version` bump) that fits every existing
  convention (dmr, error registry, CDN-Tag, throttling, OpenAPI).

**Non-Goals:**

- **No frontend implementation** (Quasar app work is listed as informative
  tasks only — separate repo, separate change).
- No local review storage as source of truth — upstream is canonical; the
  local submission log is an audit/erasure aid, never a serving path.
- No cross-client name matching in the subject recipe (rejected: fuzzy
  matching does not exist upstream; `q` must be byte-exact; the existing
  hut-review stock is ≈0 so there is nothing to lose).
- No `https`-URL subjects (rejected: ecosystem isolation — no other client
  would share them; equivalence resolution between URL and geo subjects is
  unproven live), no `urn:osm` subjects (non-standard, OSM ids unstable).
- No `did:web`/`did:plc` identity dependency (upstream `/identity` is 404
  today; keep the seam, ship without).
- No reliance on live equivalence resolution for correctness (spike task,
  informative for later aliasing).
- No Wodore-side review *content* moderation pipeline beyond blacklist +
  abuse-report relay (no pre-moderation of submissions).

## Decisions

### D1 — Subject URI recipe: `geo:<lat>,<lon>?q=<slug>&u=<radius>`

A pure function of the hut row, evaluated on demand:

```text
subject(hut) = "geo:{lat:.6f},{lon:.6f}?q={urlencode(hut.slug)}&u={u}"
```

- `lat`/`lon` from `Hut.location` (WGS84, PostGIS SRID 4326), formatted with
  **6 decimal places** (~0.1 m — avoids float-noise churn between calls).
- `q` = the **Wodore slug**, percent-encoded. Slugs are unique, byte-stable
  (renames mint a new slug via `create_unique_slug_name`; location moves are
  rare edits), ASCII, ≤25 chars — comfortably inside the ≤100-char limit.
  Names are deliberately NOT used: multilingual (`name_de`/`name_fr`/…) and
  mutable, so any name-based `q` would silently fork the subject on rename
  or translation.
- `u` = one configurable constant for all huts (see open decision O1;
  recommended default 30 m). Using a single constant keeps the recipe
  stateless (no per-hut extent storage) and the radius-sum matching
  predictable: two Wodore subjects never match each other (distinct slugs),
  and external MapComplete subjects (`q=<osm name>`, `u≈10`) never match
  Wodore subjects — an accepted trade-off given the ≈0 existing stock.
  Cross-client bridging is deferred to equivalence claims (D7).

**Alternatives considered**: `q=<OSM name>` à la MapComplete (rejected —
fuzzy matching doesn't exist upstream, names fork on translation/rename;
deliberately accepted isolation); `https://wodore.com/huts/<slug>` subjects
(rejected — HEAD-checked host, ecosystem isolation, unproven equivalence to
geo subjects); `urn:osm` (non-standard). Documented because implementers
will re-encounter these ideas when bridging later.

### D2 — Architecture: one app, one client, proxy everything

New Django app `server/apps/reviews`:

```text
server/apps/reviews/
  models.py        # ReviewerKey, ReviewerProfile, SubmittedReview, ReviewBlacklist, OsmLinkCandidate
  client.py        # MangroveClient (httpx) + subject recipe
  signing.py       # ES256 JWT construction per MaReSt (header kid+jwk, claims, actions)
  services.py      # read/write orchestration: validation, quota, cache invalidation, blacklist filter
  cache.py         # subject-keyed read cache + write-through invalidation
  api.py           # dmr controllers (`paths`)
  admin.py         # Unfold: blacklist, submission log, OSM link queue, reviewer keys
  management/commands/reviews_osm_sync.py, reviews_erase_user.py
```

`MangroveClient` is the **only** code allowed to talk to
`api.mangrove.reviews` (base URL from `MANGROVE_API_BASE_URL`, default
production; overridable to a local/staging instance). httpx client with
explicit connect/read timeouts (open decision O8 for numbers; ~5 s connect /
10 s read), bounded retries **only for idempotent GETs** (never for
`PUT /submit`), one structlog event per request with Sentry span
(`mangrove.request`), and error translation: timeouts/5xx/DNS → a single
internal `UpstreamUnavailable` exception; upstream 4xx (e.g. 400 on a
rejected JWT) surfaces its body verbatim into logs but maps to a
sanitized `APIError` for clients (never relay raw upstream bodies).

**Contract pinning**: the client's request shapes and expected response
schemas (review list item, subject aggregate, issuer stats, batch response)
are pinned as recorded fixtures under
`server/apps/reviews/fixtures/mangrove/` (one JSON per endpoint, captured
from live 0.2.0) + pydantic models that parse them. Contract tests replay
the fixtures; a documented `python -m server.apps.reviews.recapture` helper
(never in CI) re-records them. Upstream drift therefore fails CI loudly
while runtime parses defensively (unknown fields ignored, missing fields
→ `UpstreamUnavailable`-style degradation, never a 500 with a stack trace).

### D3 — API surface (dmr, additive)

All controllers subclass `server.apps.api.controller.ApiController`; every
route sets `name=` == `@modify(operation_id=…)`; errors via the RFC 9457
registry; `Api-Version` middleware applies automatically; throttles via the
existing dmr throttling stack. Sketch (exact field names = open decision O5;
shapes below are the recommendation to finalize in implementation):

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /v1/huts/{slug}/reviews` | none | Proxied, paginated review list for the hut's subject; envelope `{"data": […], "count": N}`; `lang` query like other hut endpoints |
| `GET /v1/huts/{slug}/reviews/summary` | none | Single-hut aggregate (count, rating mean from upstream `GET /subject/{sub}`, positives) |
| `POST /v1/huts/reviews-summary` | none | Batch aggregates for map badges — body/slugs list (bounded), fed by upstream `POST /batch` |
| `POST /v1/huts/{slug}/reviews` | `AuthBearer` | Submit (rating and/or opinion, images, metadata subset) — server signs + relays; returns the created review incl. its `signature` |
| `PATCH /v1/huts/{slug}/reviews/{signature}` | `AuthBearer` | Edit — signed `action: edit` against `urn:maresi:{signature}` |
| `DELETE /v1/huts/{slug}/reviews/{signature}` | `AuthBearer` | Delete — signed `action: delete` |
| `POST /v1/huts/{slug}/reviews/{signature}/report` | `AuthBearer` | Report abuse — signed `action: report_abuse` with reason as `opinion` |
| `GET /v1/me/reviews` | `AuthBearer` | The caller's reviews (upstream `GET /reviews?kid=`, hut slugs resolved by resolving each `sub` back to a hut) |

Huts that are not public/active → `raise_not_found` (no subject leakage).
Reads of huts with zero reviews return an empty list / zero-count summary —
the upstream 404-for-unknown-subject is normalized away.

Submitted review DTO: `{rating?: 0–100, opinion?: ≤1000, images?: [{src, label?}]×≤5,
nickname?, language?, experience_context?, is_personal_experience?, is_affiliated?}`.
Server-side metadata enrichment: `client_id` = the Wodore frontend origin
(config), `license` = `CC-BY-4.0` (default; see D9), `osm_id` from the
hut's OSM linkage (D6) when present, `language` defaulting from the request
language. Validation rejects anything outside the MaReSt metadata allowlist
we choose to accept (error codes `review_invalid_*`).

Every new endpoint is additive → **no `Api-Version` bump, no snapshot
transform**; new error codes on new endpoints are additive by the runbook's
litmus test.

### D4 — Identity: one server-held keypair per account

- `ReviewerKey` (1:1 with `User`, created lazily on first write): ES256
  P-256 keypair; **private JWK encrypted at rest** (Fernet/
  `cryptography.fernet.MultiFernet` under a dedicated
  `MANGROVE_KEY_ENCRYPTION_KEY` env secret from Infisical — *not* the
  Django `SECRET_KEY*, so key rotation and app secret rotation stay
  independent); `kid` = PEM public key (whitespace-normalized, since the
  standard says PEM whitespace is insignificant), indexed for reverse
  lookup (which user wrote this review?).
- `ReviewerProfile` (1:1 with `User`): display `nickname` (default: a
  minted non-identifying name, never the account email — Mangrove is a
  public dataset and PII must not leak into it), preferred review
  `language`.
- `signing.py` builds MaReSt JWTs: header `{alg: ES256, typ: JWT, kid: <pem>,
  jwk: <json string with key_ops: ["verify"]>}`, claims per action type.
  The **private key never leaves the server** except through the owner-only
  export endpoint (below).
- **Ownership enforcement**: edit/delete accepted only when the target
  review's `kid` equals the caller's current `ReviewerKey.kid` — enforced
  locally (via the upstream `GET /review/{signature}` check or our
  `SubmittedReview` log) *before* signing; report_abuse needs no ownership
  (signed with the reporter's key).
- **Import/export (opt-in, later phase)**: `GET /v1/me/reviews/identity`
  exports the private JWK string (same format MapComplete/mangrove.reviews
  use, so it round-trips); `PUT` imports an existing JWK — re-derives its
  `kid`, rebinds the account (one key per account at a time), and from then
  on edits/deletes of that identity's reviews work. This is how a user
  brings their MapComplete identity and sees one cross-client track record.
  Deferred to a later task phase; **not** part of the first release cut.
- **Future notes (informative, no dependency)**: OSM-preference
  import/export (MapComplete stores the JWK in OSM user preferences under
  namespace `mangrove`, key `identity` — import would need the user's OSM
  OAuth or a paste flow); `did:web` identity binding once upstream
  `/identity` is live. The `kid`-keyed model keeps both addable without
  schema change.
- **GDPR erasure**: `reviews_erase_user <user>` management command (and an
  account-deletion hook) signs `delete` actions for every review in the
  user's `SubmittedReview` log, waits for relay, then destroys key +
  profile + log rows. Reviews authored via an *imported* key that predate
  the account cannot all be enumerated (only those visible via
  `GET /reviews?kid=` — fetch and delete all of them too).

### D5 — Write path, moderation, quota

1. `AuthBearer` gate → user + `ReviewerKey` (minted lazily).
2. **Quota**: per-user rolling window (default recommendation: 5
   submissions/day, 20 edits+deletes/day; open decision O7) → 429
   `review_quota_exceeded` with reset time (mirrors the
   `anonymous-availability-quota` error shape).
3. **Validation** (D3 DTO + MaReSt limits: rating 0–100 int, opinion
   ≤1000, images ≤5, label ≤50, metadata allowlist) → `400
   review_invalid_*`.
4. Sign JWT (`signing.py`), `PUT /submit/{jwt}` via `MangroveClient`;
   upstream 2xx → record in `SubmittedReview` (append-only: user, hut
   slug, subject URI, action, `iat`, **signature**, full JWT) →
   **write-through cache invalidation** for that hut's list + summary
   (+ batch-summary subject key) → respond 201/200 with the review.
5. Upstream failure → 503 `upstream_unavailable` (never a half-written
   local state; the submission log records attempts for reconciliation).

**Moderation**: `ReviewBlacklist` rows (signature, reason, created_by)
exclude reviews from Wodore-served listings/summaries (filter after fetch;
admin-managed via Unfold) — a local visibility decision that never mutates
the open dataset. Abuse reports from users are relayed as signed
`report_abuse` actions so the upstream moderation queue sees them; staff
can additionally blacklist locally. No pre-publication moderation (spam is
rate-limited by quota + auth; the dataset is open and others mirror it —
hiding here is a serving decision).

### D6 — Read path, caching, CDN

- **Local cache** (Django cache framework): keyed by subject URI (+lang +
  pagination window) for lists, by subject for summaries; TTL minutes-scale
  (recommendation 5 min lists / 15 min summaries; O8). Successful writes by
  our own users invalidate immediately (write-through); foreign reviews
  appear on TTL expiry — acceptable for reviews (not booking-critical).
- **CDN**: list/summary responses get `Cache-Control` (via
  `@modify(headers=cache_headers(...))`) + CDN-Tag `api:reviews`
  (`ApiCdnCacheMiddleware` taxonomy); our writes purge the tag+subject.
  The submit/action endpoints are `no-store`.
- **ETag interplay (open decision O3)**: recommendation — **do not fold
  reviews into hut-detail ETags at all**. Reviews live on their own
  endpoints; hut endpoints and their ETags stay review-blind. The frontend
  composes hut detail + reviews client-side. This keeps review volatility
  (anyone in the world can add one at any moment — invalidation would need
  TTL anyway) from wrecking the hut cache; revisit only if we later embed
  summary chips into `GET /v1/huts/{slug}` (then as a separately-cached
  fragment or a `?include=` param with its own key).
- **Hut-detail badges**: the batch-summary endpoint serves map badges
  (bounded slug lists; chunked upstream `POST /batch`); cached like
  summaries. `min(zoom)`-driven batching is a frontend concern.

### D7 — Equivalence: bridge later, verify first

Upstream equivalence claims (`{sub: source, action: equivalence, opinion:
target}`, any key signs, server-side union-find weighted by issuer
credibility ≥ one average reviewer; **live resolution status on
api.mangrove.reviews unverified**) are the designated future bridge between
Wodore slug subjects and MapComplete OSM-name subjects: Wodore's reviewer
identity (which accrues credibility by reviewing) files claims like
`geo:…?q=<slug> ≡ geo:…?q=<osm-name>`. Until verified live, Wodore
**neither submits nor relies on equivalence** — a small spike task
(informative, implementation-phase) checks actual resolution behavior
against test subjects (`geo:0,0?q=Test&u=100` is a reserved test URI) and
documents it; the signing service keeps a generic action builder so filing
claims later is code-light. ORA contact for ecosystem questions:
hello@open-reviews.net (links/Matrix/Mastodon on open-reviews.net) —
relevant both for equivalence status and partner onboarding (Swiss tourism
portals are ORA partners).

### D8 — OSM linkage batch job

A recurring django-q2 job (management command `reviews_osm_sync`, scheduled
like availability sync; precedent `server/apps/huts/management/commands/huts.py`):

- **Input**: every public+active hut; skip huts with a *verified current*
  OSM link unless re-checking (`--refresh` / weekly full pass).
- **Overpass query** around each hut location (bbox ~500 m):
  `nwr[tourism~"^(alpine_hut|wilderness_hut|cabin| hut|apartment|guest_house|hotel)$"]`
  — final tag set to tune during implementation (the hut import's OSM
  source already encodes the relevant vocabulary).
- **Scoring**: distance (hut location ↔ element center) + name similarity
  (existing `pg_trgm` GIN index on `huts.name` — `hut_name_gin_idx` — is
  the precedent) → unique best candidate above threshold (e.g. ≤200 m AND
  similarity ≥0.5, tunable) ⇒ write/update a `HutSource` row with
  organization `osm` (existing pattern: `source_id` = numeric id,
  `source_data` = `{osm_type, id, version?, center_lat/lon, tags: subset}`).
- **Ambiguity queue**: multiple/tentative candidates ⇒ `OsmLinkCandidate`
  row (hut, candidates JSON, scores) surfaced in Unfold admin with
  accept/reject actions; accepted candidates write the `HutSource`.
- **Politeness**: single-threaded, rate-limited Overpass usage (instance
  configurable), exponential backoff on 429; ODbL attribution lives in the
  existing OSM org/source records. No permission from anyone needed for
  Overpass reads; operator contact is unnecessary for linkage (relevant
  only if we later want operator-flagged reviews, e.g. `is_affiliated`).
- **Consumption**: at submit time the service resolves the hut's OSM link
  and stamps `metadata.osm_id` = `<osm_type>/<source_id>` (+`/<version>`
  when the sync captured one) — the standard's format for unstable-by-design
  ids, which is why the *subject* stays slug-based (D1).

### D9 — Images, legal, data sovereignty

- **Images (open decision O4)**: recommendation v1 = relay client-supplied
  `images[].src` URLs (https, publicly fetchable, ≤5) — the upstream
  server fetches and persists them (S3 on their side), so Wodore needs no
  image pipeline for reviews and images outlive the source URL. Validation:
  URL shape + count + label length only (no local fetch on the request
  path; a HEAD pre-check is optional hardening). Deferred alternative:
  Wodore-side upload through the existing `images` app (+imagor) with the
  public URL handed to Mangrove — better privacy story for EXIF/attribution
  and consistent CDN delivery, at the cost of a new upload flow; keep the
  DTO identical so the backend swap is invisible to clients.
- **License/attribution**: reviews are CC-BY-4.0 by default (MaReSt
  default; the DTO never sets another SPDX id in v1). Read responses carry
  an envelope field `license: "CC-BY-4.0"` + `attribution` pointing at
  mangrove.reviews / the ORA, so frontends can attribute without hardcoding
  (the actual attribution rendering is a frontend task).
- **ORA terms**: submitters publish into the Mangrove dataset under the
  ORA Terms of Service; the submit endpoint description (OpenAPI) and the
  frontend form (informative task) must say so — Wodore relays a
  publication, it does not own the review. `nickname` is the only
  identity-ish data we put upstream; it must never default to email/name.
- **Data sovereignty / archival**: upstream is the canonical store and is
  open data — anyone can export it (`GET /reviews?sub=` per subject; ORA
  publishes dumps). For our own submissions, the `SubmittedReview` log
  *is* the archival record (JWT verbatim — independently verifiable
  signatures); a small periodic q2 job (or the erasure command's export
  mode) can dump it. Wodore can reconstruct its review corpus from the log
  + upstream reads even if our DB is lost, and can walk away from ORA
  without losing authorship records.

### D10 — Settings, env, observability

Settings component `server/settings/components/reviews.py` (Infisical-backed
decidables with dev/test defaults): `MANGROVE_API_BASE_URL`,
`MANGROVE_TIMEOUT_CONNECT/READ`, `MANGROVE_U_RADIUS` (O1),
`MANGROVE_CACHE_TTL_LIST/SUMMARY`, `MANGROVE_QUOTA_SUBMIT/EDIT`,
`MANGROVE_KEY_ENCRYPTION_KEY`, `MANGROVE_CLIENT_ID` (frontend origin for
`metadata.client_id`), `MANGROVE_OVERPASS_URL`. Sentry: spans around every
upstream call, breadcrumbs on submit; PII rules apply (never log opinions
or nicknames at info level — they'd flow into breadcrumbs). Local auth
(dev) works end-to-end: `AuthBearer` already accepts local tokens, so
review writing is testable without Zitadel.

## Risks / Trade-offs

- [Upstream API is 0.2.0, not frozen — breaking drift] → contract fixtures
  + pydantic pins fail CI early; defensive parsing maps drift to
  `upstream_unavailable`, never a 500; client adapter is one module.
- [Upstream outage/outage-of-record] → read caches serve stale-within-TTL;
  writes fail 503 (honest — reviews are not booking-critical); consider
  `stale-if-error` header hardening later.
- [Wodore holds users' private keys — custody liability] → encrypted at
  rest with a dedicated rotatable secret (MultiFernet: add-new-keep-old),
  export gives users self-custody, erasure destroys; document in ToS.
- [Loss of encryption secret = keys unrecoverable (users lose edit/delete
  of past reviews)] → MultiFernet old-key retention + Infisical secret
  history + the `SubmittedReview` log still allows *support-assisted*
  nothing (by design — accept and document; export-before-rotation
  runbook step).
- [Slug-based subjects isolate us from MapComplete stock] → accepted
  (stock ≈0); equivalence claims are the designated bridge (D7), and
  slugs are the only stable multilingual-proof identifier we own.
- [Hut location edit changes the subject URI] → rare, manual, editor-level
  action; mitigation documented: reviews live on the old subject; an
  equivalence claim (future) re-links; optionally a "relocate" admin
  action files one automatically once equivalence is verified live.
- [Quota/gaming: accounts are free] → auth gate + per-user quota +
  upstream credibility system does the heavy lifting; blacklist hides
  locally; revisit with feedbacks-style heuristics only if abuse observed.
- [Overpass rate limits / OSM data quality] → polite rate limiting,
  ambiguity queue instead of auto-linking dubious matches, weekly cadence.
- [PII leakage into an open dataset] → nickname-only policy (minted
  defaults), metadata allowlist, no email/real-name fields accepted,
  documented in the submit endpoint description.

## Migration Plan

Purely additive: new app + tables (no changes to existing tables), new
endpoints, q2 schedule entries, env secrets. Rollout: deploy backend →
seed nothing (subjects are computed, links sync on first job run) →
frontend later. Rollback: disable the app's endpoints via feature flag
(env kill-switch `MANGROVE_ENABLED` gating the write path at minimum) or
revert deploy — no data migration involved. Contract recapture and OSM
sync are ops-run commands, not deploy steps.

## Open decisions

Each item below is deliberately unresolved at proposal time; the
recommendation is what implementation should do unless new information
(e.g. the equivalence spike) says otherwise.

- **O1 — `u` radius policy.** Constant vs per-hut extent (way-huts span
  50–200 m; clustered sites like hut+winterroom+bivouac sit within ~50 m).
  *Recommendation*: constant `u=30` for v1 (simple, predictable matching,
  no extent storage); revisit per-hut extent (max center→vertex distance
  from OSM geometry, MapComplete's polygon recipe) when the linkage job
  makes extents cheaply available. A larger `u` only widens *incoming*
  match tolerance from foreign subjects with the same `q` — with slug
  `q`s that is moot today.
- **O2 — Equivalence-resolution spike.** Verify on api.mangrove.reviews
  whether union-find resolution is actually live for reads (submit claim
  between two reserved test subjects, check aggregation). *Recommendation*:
  run as an early implementation-phase investigation task; outcome gates
  any future aliasing/bridging work, not v1 behavior.
- **O3 — ETag interplay on hut endpoints.** *Recommendation*: keep hut
  endpoints review-blind (separate endpoints, D6) — no `Api-Version` or
  ETag churn; revisit only if product wants summary chips embedded in hut
  detail.
- **O4 — Image hosting.** Relay client URLs (upstream persists) vs
  Wodore-side upload via the existing `images` app + imagor.
  *Recommendation*: relay URLs for v1 (DTO identical either way); add
  Wodore-hosted upload as a follow-up if EXIF/privacy/CDN concerns
  materialize.
- **O5 — Exact endpoint/DTO shapes.** The D3 table + DTO sketch is the
  recommendation; final names/fields (e.g. `PATCH`-vs-`PUT` for edit,
  `reviews-summary` vs `/v1/reviews/summary`, list item field set incl.
  whether `signature` is named `id`) get settled in the implementation PR
  against the OpenAPI docs review — all additive, no version impact.
- **O6 — Rating ↔ stars mapping.** Upstream rating is 0–100 "likelihood to
  recommend"; stars are a pure frontend concern (MapComplete maps 5 stars
  to 0/25/50/75/100). *Recommendation*: API stays integer 0–100, accepts
  exactly those five values or any int (decide: *any int*, frontend sends
  star-quanta); frontend renders stars. Document the mapping in the
  endpoint description so clients stay consistent.
- **O7 — Quota defaults.** *Recommendation*: 5 submissions/day/user, 20
  edit+delete/day/user, no report quota (throttle-scoped instead);
  settings-tunable, start strict, loosen with data.
- **O8 — Timeouts & cache TTLs.** *Recommendation*: connect 5 s / read
  10 s, 2 retries (GETs only); TTL 5 min lists, 15 min summaries,
  batch-summary 15 min. Tune with Sentry trace data.
