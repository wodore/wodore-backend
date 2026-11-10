# Design: reviews-mangrove

## Context

**Open Reviews** (Open Reviews Association, ORA) is a decentralized review
system: a review is an ES256-signed JWT (Mangrove Review Standard, MaReSt
v0.7.0) stored on the Original Mangrove Server at `https://api.mangrove.reviews`
(**Server API 0.4.1** — live, CORS-open, *not frozen*). The dataset is open
data (CC-BY-4.0 by default per the Terms of Service; a full-dataset dump is
published daily via `GET /dump` → S3). Existing consumers: MapComplete
(stores the reviewer's private JWK in OSM user preferences), the
mangrove.reviews web app (localStorage), and Swiss tourism portals. The full
dataset dump (2026-11-08, 14 504 reviews; 11 548 geo subjects; 539 with
images) contains **zero alpine-hut reviews** — Wodore would be the first
mover for huts.

Upstream facts below were verified live on 2026-11-08 (§0 spike; probes
against the reserved test-subject family only; see tasks §0 and the spike
log in `_work/261108_mangrove_spike.md`):

- **Subject** (`sub` claim): core URI schemes `https` (server HEAD-checks
  public host on submit), `geo:lat,lon?q=…&u=…` (RFC 5870 with query-string
  parameters; `q` required ≤100 chars, `u` = uncertainty radius in meters,
  0 < u ≤ 10000), `urn:isbn`, `urn:lei`, `urn:maresi` (references another
  review by signature), `did:` (identity actions).
- **geo matching (live-verified)**: two geo subjects match iff their `q`
  strings are equal **after normalization — case- and
  punctuation-insensitive** (`q=Test` ≡ `q=test` ≡ `q=Te.st`, verified;
  accent folding did NOT match in the probe: `q=tÉst` ≢ `q=Test`) AND
  coordinates within the *sum* of both `u` values. `GET /reviews?sub=` also
  includes subjects joined by accepted equivalence claims (per docs).
  A subject without `q` matches on location alone — never emit one.
- **Actions**: `edit` / `delete` / `report_abuse` (all `sub` =
  `urn:maresi:<signature of the target review>`; edit/delete MUST be signed
  by the original key; report_abuse by any key and MUST NOT carry a
  rating), `equivalence` (asserts two subject URIs denote the same entity;
  resolved server-side by union-find weighted by issuer credibility ≥ one
  average reviewer — a fresh key weighs 0), `identity`/`profile`
  (`did:web`/`did:plc`; `/identity/{id}` endpoints exist on 0.4.1 —
  available but not needed for v1; keep the seam, ship without).
- **Submit (0.4.1)**: `POST /submit` with the JWT as a `text/plain` body
  (`PUT /submit/{jwt}` is deprecated — and would leak opinion text into
  URL logs; never use it). Response is the literal body `true` (200) —
  **no signature is returned**; derive it locally as the JWT's third
  base64url segment. Opinion-only and rating-only submissions are both
  accepted (live-verified; the docs' "requires rating" note is wrong).
  Re-submitting a deleted review, its edits or the delete itself is
  refused — erasure must treat that refusal as success (idempotent).
- **`GET /reviews` (0.4.1)**: params `sub`, `kid`, `q`, `signature`,
  `gt_iat`, `limit` (default 1000, >3500 → 400), `offset`,
  `latest_edits_only` (**default true** — upstream already collapses
  edits; items carry `original_sub` for edits), `min_credibility`,
  `examples`, `issuers`, `maresi_subjects`. Response:
  `{reviews: [{did?, geo?, jwt, kid, original_sub?, payload, scheme,
  signature}], issuers?, maresi_subjects?}`. Action rows (equivalence,
  identity, …) are excluded from listings unless `action` is passed.
  Geo URIs in `?sub=` must be sent as properly encoded query values, and
  as percent-encoded path segments for `/subject/{sub}`.
- **Aggregates** `GET /subject/{sub}` / `POST /batch`:
  `{sub, quality (undocumented semantics; null when empty), count,
  opinion_count, positive_count, confirmed_count}`. `quality` is not
  provably a mean, blacklist entries cannot be subtracted, and only
  `GET /reviews?sub=` is documented to apply geo/equivalence matching —
  so **Wodore computes all aggregates locally** (D6).
- **Equivalence resolution (live-verified)**: a claim filed by a
  zero-credibility key does NOT surface foreign reviews in
  `GET /reviews?sub=` of the target (probe: distinct `q` at ~111 m,
  claim accepted, no cross-listing). Either resolution is not live in
  reads or the credibility weighting correctly zeroes fresh keys — in
  both cases random fresh keys cannot inject reviews into our listings;
  a *credible* third party theoretically could. Defense: the local
  geo-match filter (D6).
- **Images**: standard field `images` ≤5 × `{src: URL, label ≤50}`; the
  upstream server fetches and persists them — the 2026-11-08 dump shows
  1022 of 1025 persisted image URLs on `files.mangrove.reviews`.
- **Identity is the keypair**: `kid` = PEM public key (whitespace in the
  PEM is insignificant — servers compare normalized; store it
  normalized); all reviews of one identity via `GET /reviews?kid=`. No
  OAuth anywhere upstream. The standard explicitly blesses "a review
  submitting service which manages user keys in a centralized fashion" —
  exactly the Wodore model below.

**Wodore facts** (verified in-repo): `Hut`
(`server/apps/huts/models/_hut.py`) has a unique `slug` (SlugField, 50
max; the generator's 25 is only a default; renames keep the slug — it is
regenerated only on an explicit slug edit), PostGIS `location` Point
(WGS84), multilingual names (modeltrans, `main_language`); 1585
public+active huts in dev. `HutSource` rows with organization slug `osm`
link 1166 huts (1406 rows including non-current: 480 node, 926 way);
`source_id` = bare numeric OSM id, `source_data` JSON with `osm_type`,
`tags`, `center_lat/lon`; `HutSource.version` is Wodore's internal
revision counter, **not** an OSM element version. django-q2 is the
batch-job precedent (erasure command); dmr controllers serve `/v1/` with
the shared error contract (RFC 9457 members), `Api-Version` middleware,
and the CDN-Tag taxonomy (tag derived from the first path segment);
`AuthBearer` (`server/apps/api/auth.py`) validates built-in/local tokens
(the token payload lands on `request.auth`, `sub` = user pk for the local
provider; `request.user` is only set for session auth — resolve the
caller from either, D4); `/v1/my/` + `MyApiController`
(`server/apps/external_links/api.py`) is the user-scoped namespace (401,
`private, no-store`, never a CDN candidate). The custom `User`
(`accounts`) is email-identity with UUID pk. No controller in the repo
serves more than one HTTP method per URL — and the API-versioning system
check (E003/E004) keys URL names 1:1 to operation ids, so **every route
below is one operation per path**.

Everything below was decided with the owner during planning; the §0 spike
(2026-11-08) settled the upstream unknowns. Remaining open decisions are
marked O1–O8 with recommendations.

## Goals / Non-Goals

**Goals:**

- Hut reviews readable by anonymous clients and writable by Wodore accounts,
  with all Mangrove traffic proxied through the backend (no client-side
  upstream calls, no upstream key material in browsers).
- A **deterministic, stable subject URI per hut** so reviews survive
  renames, translations and portal churn, with verified-uniqueness under
  upstream's normalized matching.
- Server-side key custody that makes edit/delete/report/GDPR-erasure
  possible for logged-in non-crypto users, with encrypted-at-rest private
  keys and an append-only local record of what we submitted.
- Upstream-resilient reads (local caching + timeouts + graceful
  degradation) and a **pinned contract** so upstream 0.4.x drift fails our
  tests, not production requests.
- An additive API (no `Api-Version` bump) that fits every existing
  convention (dmr, error registry, `/v1/my/`, throttling, OpenAPI).

**Non-Goals:**

- **No frontend implementation** (Quasar app work is listed as informative
  tasks only — separate repo, separate change).
- No local review storage as source of truth — upstream is canonical; the
  local submission log is an audit/erasure aid, never a serving path.
- No cross-client name matching in the subject recipe (rejected: upstream
  matching is normalized-equality at best; names fork on translation and
  rename; the existing hut-review stock is 0 so there is nothing to lose).
- No `https`-URL subjects (rejected: ecosystem isolation; equivalence
  bridging to geo subjects unproven), no `urn:osm` subjects (non-standard,
  OSM ids unstable).
- No dependency on `did:web`/`did:plc` identity or on live equivalence
  resolution for correctness (keep the seam, ship without; §0 spike
  recorded the current behavior).
- No CDN purge integration in v1 (no Bunny purge client exists in the
  backend; short TTLs + local write-through invalidation suffice — D6).
- No Wodore-side review *content* moderation pipeline beyond blacklist +
  abuse-report relay (no pre-moderation of submissions).
- No import/export endpoints in the first release (phase 2 — D4).

## Decisions

### D1 — Subject URI recipe: `geo:<lat>,<lon>?q=<review-name>&u=<radius>`

A pure function of the hut row **plus the hut's pinned review name**:

```text
q = review_name(hut)      # pinned name → OSM name → hut name
subject(hut) = "geo:{lat:.6f},{lon:.6f}?q={urlencode(q)}&u={u}"
```

- `lat`/`lon` from `Hut.location` (WGS84), 6 decimal places (~0.1 m).
- **Review name resolution** (owner decision, 2026-11-08 round 2):
  1. `HutReviewSubject.name` — **pinned on the first review write**
     (`pin_review_name`), so later OSM renames or hut renames can never
     fork the subject of a hut that already has reviews;
  2. before any review exists: the OSM name (current `HutSource`, org
     `osm`, its `name` column);
  3. fallback: the hut's own name.
- Motivation: OSM-name `q`s are what MapComplete emits — Wodore subjects
  become cross-client matchable (same normalized `q` + coordinates within
  the radius sum) instead of deliberately isolated. The slug recipe
  (round 1) is superseded.
- **`q` encoding rule (live-verified 2026-11-08, round 3)**: spaces
  MUST be plus-encoded at submit (`q=Test+Hut` accepted, `q=Test%20Hut`
  refused upstream with 400); matching accepts both forms; accents are
  percent-encoded UTF-8 (`café` → `caf%C3%A9`) and accents do NOT fold
  in matching. `urlencode` — exactly what `build_geo_subject` uses —
  is the correct encoder (MapComplete-compatible).
- Trade-off (accepted): hut names are not unique — two huts with the same
  normalized name within 2·u (60 m) would share reviews. Rare in the
  corpus; the normalized-name collision check stays as an operator
  warning, not a hard invariant. Pin-on-first-write keeps any single
  hut's subject stable for its lifetime.
- Rejected alternatives (kept for future implementers): slug `q`
  (round 1 — stable but isolated), name-based without pinning (forks on
  rename), `https` URL subjects, `urn:osm`.

### D2 — Architecture: one app, one client, proxy everything

New Django app `server/apps/reviews`:

```text
server/apps/reviews/
  models.py        # ReviewerKey, ReviewerProfile, SubmittedReview, ReviewBlacklist
  client.py        # OpenReviewsClient (httpx) + subject recipe + geo-match filter
  signing.py       # ES256 JWT construction per MaReSt (cryptography, DER→raw)
  services.py      # read/write orchestration: validation, quota, cache, blacklist, aggregates
  cache.py         # subject-keyed read cache + write-through invalidation
  api.py           # dmr controllers (`paths`, `my_paths`)
  admin.py         # Unfold: blacklist, submission log, reviewer keys
  management/commands/reviews_erase_user.py
```

`OpenReviewsClient` is the **only** code allowed to talk to
`api.mangrove.reviews` (base URL from `ORA_API_BASE_URL`, default
production; overridable to a local/staging instance). httpx client with
explicit connect/read timeouts (5 s / 10 s, O8), bounded retries **only
for idempotent GETs** (never for submits), one structlog event per
request with a Sentry span (`mangrove.request`), and error translation:
timeouts/5xx/DNS/unparsable → a single internal `UpstreamUnavailable`
exception; upstream 4xx surfaces its body verbatim into logs but maps to
a sanitized `service_unavailable` APIError for clients (never relay raw
upstream bodies).

**Signing** (`signing.py`) uses `cryptography` directly (P-256 ECDSA with
SHA-256; DER signature decoded to the raw r‖s JWS form) — fully typed, no
partially-typed JOSE dependency. The derived review signature is the
JWT's third base64url segment (upstream returns none).

**Contract pinning**: request/response shapes pinned to **0.4.1** as
recorded fixtures under `server/apps/reviews/fixtures/mangrove/` (one
JSON per endpoint, captured live against **reserved test subjects only**
— `geo:0,0?q=Test&u=100` family, `https://example.com`,
`urn:isbn:9780000000002`, `urn:lei:00000000000000000098` — never against
real subjects) + pydantic models that parse them. Contract tests replay
the fixtures; a documented dev-only recapture helper re-records them
(never in CI). Upstream drift fails CI loudly while runtime parses
defensively (unknown fields ignored; missing essential fields →
`UpstreamUnavailable`, never a 500).

### D3 — API surface (dmr, additive, one operation per path)

All controllers subclass `server.apps.api.controller.ApiController`
(user-scoped ones subclass `MyApiController`); every route sets `name=` ==
`@modify(operation_id=…)` (E003/E004 invariant — hence **no path carries
two HTTP methods**); errors via the RFC 9457 registry; the Api-Version
middleware applies automatically; reads get explicit dmr throttles.

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /v1/huts/{slug}/reviews` | none | Proxied, locally paginated review list (`limit` ≤100, `offset`; default 20) — `get_hut_reviews` |
| `GET /v1/huts/{slug}/reviews/summary` | none | Locally computed aggregate — `get_hut_reviews_summary` |
| `GET /v1/reviews/summary?slugs=a,b,c` | none | Batch aggregates for map badges (≤50 slugs, canonicalized) — `get_reviews_summary_batch` |
| `POST /v1/huts/{slug}/reviews/submit` | `AuthBearer` | Submit (rating and/or opinion, images, metadata subset) — server signs + relays; 201 with the created review incl. its derived `signature` — `submit_hut_review` |
| `POST /v1/huts/{slug}/reviews/{signature}/edit` | `AuthBearer` | Edit — signed `action: "edit"` against `urn:maresi:{signature}` — `edit_hut_review` |
| `POST /v1/huts/{slug}/reviews/{signature}/delete` | `AuthBearer` | Delete — signed `action: "delete"` — `delete_hut_review` |
| `POST /v1/huts/{slug}/reviews/{signature}/report` | `AuthBearer` | Report abuse (reason required) — signed `action: "report_abuse"` — `report_hut_review` |
| `GET /v1/my/reviews` | `MyApiController` | The caller's reviews with hut-slug annotation — `get_my_reviews` |

Huts that are not public/active → `raise_not_found` (no subject leakage).
Zero-review huts → empty list / zeroed summary (upstream 404 normalized
away). Edit/delete/report additionally 404 when the target review's
`sub`/`original_sub` does not match the hut's subject (prevents acting on
arbitrary signatures through a hut URL). The list endpoint carries no
`lang` parameter — reviews are multilingual by their own `language`
metadata; filtering by language, if ever needed, is a future additive
param.

Submitted review DTO (pydantic, `extra="forbid"` → unknown keys are
standard `validation_error`s): `{rating?: int 0–100, opinion?: ≤1000 code
points, images?: [{src: https URL, label?: ≤50}] ×≤5, nickname?: ≤50,
language?: BCP 47 ≤35, experience_context?: ≤20
(business|family|couple|friends|solo), is_personal_experience?: true,
is_affiliated?: true}` — MaReSt flag semantics: flags are sent **only
when true**, never `false`. Edit DTO: same, at least one of
rating/opinion. Report DTO: `{opinion: required ≤1000}`. Server-side
enrichment: `client_id` = `ORA_CLIENT_ID`, `license: CC-BY-4.0`,
`osm_id` from the hut's OSM linkage when present (D8), `nickname`
defaulting from the reviewer profile (DTO value overrides), `language`
defaulting from the request language, `iat` = now.

Every endpoint is additive → **no `Api-Version` bump**; `api_snapshot` is
regenerated by CI convention but nothing is committed and no transforms
are registered (additive changes need no snapshot in the PR).

### D4 — Identity: one server-held keypair per account

- `ReviewerKey` (1:1 with `User`, **`on_delete=PROTECT`**, created lazily
  on first write): ES256 P-256 keypair; **private JWK encrypted at rest**
  (Fernet/`MultiFernet` under a dedicated `ORA_KEY_ENCRYPTION_KEY`
  env secret from Infisical — *not* the Django `SECRET_KEY`, so rotations
  stay independent); `kid` = single-line PEM public key
  (whitespace-normalized — upstream compares PEMs ignoring whitespace),
  unique-indexed for reverse lookup (which user wrote this?).
- `ReviewerProfile` (1:1, `on_delete=PROTECT`): display `nickname`
  (default: a minted non-identifying name — never derived from account
  data; the DTO's optional per-review `nickname` overrides it) and
  preferred review `language`.
- `signing.py` builds MaReSt JWTs: header `{alg: ES256, typ: JWT,
  kid: <pem>, jwk: <JSON string with key_ops: ["verify"]>}`, claims per
  action type. The **private key never leaves the server** in v1
  (export/import are phase 2 — below).
- **Caller resolution**: user-scoped endpoints accept either a Django
  session user (`request.user`, as `/v1/my/` does today) or a bearer
  token whose `request.auth["sub"]` resolves to a `User` pk (built-in
  provider). The my-reviews controller extends `MyApiController` (401 +
  `private, no-store` inherited).
- **Ownership enforcement** (edit/delete, before signing): the target
  signature must exist in `SubmittedReview` with the caller's user AND
  `kid` — fallback for keys not in the log: upstream
  `GET /review/{signature}` whose `kid` equals the caller's
  (whitespace-stripped compare). Non-owned targets → 403
  (`insufficient_permission`); nothing is signed.
- **Import/export (phase 2, explicitly out of the first release)**:
  `GET/PUT /v1/my/reviews/identity` — export the private JWK string
  (MapComplete-compatible), import + rebind (re-derive `kid`, one active
  key per account). Re-authentication for export must be defined
  concretely when built (e.g. OIDC `auth_time` within N minutes). The
  `kid`-keyed model keeps this addable without schema change.
- **Future notes (informative, no dependency)**: OSM-preference sync
  (MapComplete namespace `mangrove`, key `identity`); `did:web` identity —
  upstream `/identity/{id}` exists on 0.4.1 but is not needed for v1.
- **GDPR erasure (v1)**: `reviews_erase_user <user>` management command —
  signs+relays `delete` actions for every review in the user's
  `SubmittedReview` log (re-submit-refusals after earlier deletes are
  treated as success), then destroys key + profile + log rows (the one
  documented exception to the log's append-only rule). The PROTECT FKs
  make naive `user.delete()` fail loudly instead of silently destroying
  the only key able to sign deletes; the erasure command is the sanctioned
  path.

### D5 — Write path, quota, moderation

1. `ORA_ENABLED` kill-switch check (disabled → 503
   `service_unavailable` for writes).
2. Caller resolution → lazy `ReviewerKey` mint.
3. **Quota**: rolling 24 h window counted from `SubmittedReview` rows (no
   extra table): submissions default 5/day, edit+delete combined 20/day
   (settings `ORA_QUOTA_SUBMIT/EDIT`). Exceeded → 429
   `review_quota_exceeded` (new registered code) + `Retry-After` header +
   reset time in the body; nothing is signed or relayed. Reports are not
   quota-counted; they carry a dmr rate throttle instead.
4. **Validation** (D3 DTO; `extra="forbid"`) → standard `validation_error`.
5. Log row **before** relay (`SubmittedReview`, state `pending`), sign,
   `POST /submit` (text/plain); on 2xx → state `accepted` (+ derived
   signature); on failure → state `failed` (kept for reconciliation and
   quota honesty).
6. **Write-through invalidation** of the hut's local list/summary cache
   entries (D6); respond 201/200 with the review.
7. Upstream failure → 503 `service_unavailable`; the pending row stays
   `pending` for a later reconciliation sweep (ops task, not v1 code).

**Moderation**: `ReviewBlacklist` rows (signature, reason, created_by)
exclude reviews from all Wodore-served listings/summaries (filter after
fetch; admin-managed via Unfold) — a local visibility decision that never
mutates the open dataset. Abuse reports from users are relayed as signed
`report_abuse` actions (reason required) so the upstream moderation queue
sees them; staff can additionally blacklist locally. No pre-publication
moderation.

### D6 — Read path, caching, aggregates, CDN

- **Edit rows (live-verified, round 3)**: with the default
  `latest_edits_only`, upstream listings serve the EDIT row —
  `action: "edit"`, the edit's own `signature`, `original_sub` carrying
  the geo subject. Wodore keeps such rows (identity = the ORIGINAL
  signature parsed from the `urn:maresi` sub; blacklist checks BOTH
  signatures; geo-match on `original_sub`) — dropping them would make
  every edited review vanish (Opus B3).
- **Visibility overlay (Opus B1, round 3)**: every list build overlays
  the subject's recent accepted submission-log rows — own submits
  prepended, deleted targets dropped, edited targets patched from the
  logged JWTs — regardless of cache state or worker. All review caches
  live on the **`shared` DB cache alias** (LocMem is per-process; the
  overlay must survive gunicorn's worker fan-out).
- **Local cache** (Django cache framework): list payload keyed by
  subject, summary keyed by subject, refuges.info comments keyed by
  point id — all 15-minute TTLs (owner decision). Successful local
  writes **merge write-through**: submit prepends the just-signed review
  into the cached list, edit updates the cached copy, delete removes it.
  A plain invalidation would refetch upstream, which may briefly NOT
  include the new review yet (indexing lag, observed in the §0 spike) —
  merging makes the author's own write visible on the very next read,
  TTL or no TTL. Foreign reviews appear on TTL expiry — fine for
  reviews.
- **Aggregates are computed locally** from the cached, blacklist-filtered
  list (upstream `quality` is undocumented, `/subject`+`/batch` can't
  subtract blacklists and may not apply geo matching — Context):
  `count` (listed reviews), `rating_count` + `rating_mean` (over rated
  reviews only, rounded to 1 decimal), `positive_count` (rating > 50),
  `opinion_count`. Pagination is local too (upstream fetch is one call at
  `limit=1000`, `latest_edits_only` default true already collapses edits).
  `/batch`/`/subject` are not used in v1.
- **Anti-injection filter**: after fetching by `sub`, drop any returned
  review whose `payload.sub` (or `original_sub`) does not geo-match the
  hut's subject under upstream's own rule — normalized-`q` equality AND
  distance ≤ sum of both `u` values. This bounds what a credible
  third-party equivalence claim could pull into a hut listing (D-Context:
  fresh keys cannot — verified — but defense in depth is cheap).
- **Batch summary**: `GET /v1/reviews/summary?slugs=…` — ≤50 slugs,
  sorted/deduplicated before cache-keying (canonical form), reuses the
  per-subject cached lists (one upstream fetch per cold subject), dmr
  rate-throttled. A GET so anonymous CDN caching works.
- **CDN (v1 stance)**: no purge client, no tag overrides. Anonymous reads
  set `Cache-Control: public, max-age=120` (short — foreign-review lag
  stays bounded); the middleware derives `CDN-Tag` from the path
  (`api:huts` for hut-scoped routes, `api:reviews` for the batch route) —
  informational only in v1. Authenticated responses are forced
  `private, no-store` by the middleware, so an author re-reading with
  their token sees their write immediately; anonymous visitors converge
  within the 120 s edge TTL. Hut endpoints and their ETags remain
  review-blind (reviews never fold into `GET /v1/huts/{slug}` payloads —
  the frontend composes; revisit only with a separately-cached include).

### D7 — Equivalence: verified status, bridge later

The §0 spike (2026-11-08) filed an equivalence claim between two reserved
geo subjects with a fresh key: the claim was accepted but did not surface
the source's reviews in the target's listing — consistent with
credibility-weighted union-find ignoring zero-weight issuers (or reads not
resolving at all). Consequences: (a) random fresh keys cannot alias
foreign reviews into Wodore listings (also enforced locally by the D6
filter); (b) Wodore's own future bridge (slug subjects ≡ MapComplete
OSM-name subjects) must be filed by a key with accrued credibility — a
later, deliberate campaign after real review volume exists. The signing
service ships a generic equivalence builder (not exposed via the API in
v1). ORA contact for ecosystem questions: hello@open-reviews.net (links/
Matrix/Mastodon on open-reviews.net) — relevant for resolution status,
partner onboarding (Swiss tourism portals are ORA partners) and upstream
contract changelogs.

### D8 — OSM metadata from the existing linkage

There is no new matching job: the hut import pipeline (hut-services `osm`
source → `HutSource` rows, org `osm`) already links 1166/1585 huts and
keeps refreshing it — gap-filling and verification stay with that
pipeline (out of scope here). The reviews app only **reads** the linkage
at submit time: resolve the hut's current row
(`HutSource.objects.filter(hut=hut, organization__slug="osm",
is_current=True)` most recent) and stamp `metadata.osm_id` =
`<osm_type>/<source_id>` — `osm_type` validated ∈ {node, way, relation},
total length ≤50. **Never** append `HutSource.version` (it is Wodore's
internal revision counter, not an OSM element version). Huts without a
link submit without the field.

### D9 — Images, legal, data sovereignty

- **Images**: the DTO accepts `https` URLs only (≤5, `{src, label ≤50}`);
  replies accept the same optional `images` list as submissions.
- **Photo upload relay** (round 5): `POST /v1/reviews/images`
  (authenticated, throttled) relays multipart photos to Mangrove's
  open upload server (`PUT https://upload.mangrove.reviews`, ≤5
  photos, ≤4.5 MB, JPEG/PNG/GIF/WebP). Wodore stores NOTHING — the
  response returns `files.mangrove.reviews/<hash>` URLs
  (content-addressed, immutable, 1-year cache; unlisted photos
  auto-deleted after a day) for the client to include in the review's
  `images[].src`. After a submit WITH images, the OpenReviewsProvider's
  gallery cache for the hut's coordinates is invalidated (otherwise
  the 24 h TTL delays new photos in the gallery).
- **Gallery provider** (round 3): `OpenReviewsProvider`
  (`server/apps/reviews/images.py`) feeds the hut's review photos into
  the standard geometries image pipeline — registered beside the other
  providers, so review photos get imagor variants, license rows
  (CC-BY-4.0 from review metadata), reviewer-nickname attribution and
  dedup scoring like any external source. Geo-match + blacklist filters
  mirror the listings; 24 h provider cache; `ORA_ENABLED` gates it.
  Served lists pass an image through only when its `src` host is on
  `ORA_IMAGE_HOST_ALLOWLIST` (default `["files.open-reviews.net"]` —
  1022 of 1025 persisted image URLs in the 2026-11-08 dump live there);
  other hosts are dropped at serving (never mutated upstream). This keeps
  Wodore pages from loading arbitrary third-party hosts (tracking pixels,
  IP leaks, unmoderated content); the upstream persistence behavior makes
  the allowlist the common case, not the exception. No server-side
  fetching of submitted URLs on the request path (no SSRF surface).
- **License/attribution**: reviews are CC-BY-4.0 by default (MaReSt
  default; the DTO never sets another SPDX id in v1). Read responses carry
  an envelope field `license: "CC-BY-4.0"` + `attribution` pointing at
  mangrove.reviews / the ORA, so frontends can attribute without
  hardcoding.
- **ORA terms**: submitters publish into the Open Reviews dataset under the
  ORA Terms of Service; the submit endpoint description (OpenAPI) and the
  frontend form (informative task) must say so — Wodore relays a
  publication, it does not own the review. `nickname` is the only
  identity-ish data we put upstream; it must never default to email/name.
- **Data sovereignty / archival**: upstream is canonical and open
  (`GET /dump` publishes the full dataset daily — verified). Our
  `SubmittedReview` log (verbatim JWTs, independently verifiable
  signatures) archives exactly what Wodore published and powers erasure +
  an admin JSONL export (D5, tasks §6).

### D10 — Settings, env, observability

Settings component `server/settings/components/reviews.py` (Infisical-backed
with safe defaults): `ORA_API_BASE_URL`,
`ORA_ENABLED` (kill-switch: false → writes 503, reads serve empty
collections), `ORA_TIMEOUT_CONNECT/READ`, `ORA_U_RADIUS` (30),
`ORA_CACHE_TTL_LIST/SUMMARY`, `ORA_QUOTA_SUBMIT/EDIT`,
`ORA_CLIENT_ID`, `ORA_IMAGE_HOST_ALLOWLIST`,
`ORA_THROTTLE_*` (read/batch burst+daily), and
`ORA_KEY_ENCRYPTION_KEY` — whose dev default is **hard-refused
outside `DJANGO_ENV=development|test`** (mirroring `LOCAL_AUTH_ENABLED`).
Sentry: spans around every upstream call, breadcrumbs on submit; PII rules
apply (never log opinions or nicknames at info level). Local auth (dev)
works end-to-end: `AuthBearer` accepts local tokens, so review writing is
testable without Zitadel (tests use the password grant +
`local_auth_users` fixture).

### D11 — Read-only provider merge: refuges.info (round 2)

Verified live 2026-11-08: ``GET https://www.refuges.info/api/commentaires?
id_point={id}&format=json`` returns a dict keyed by index (or a list on
older deployments); each item carries ``id_commentaire``,
``auteur_commentaire``, ``date_commentaire`` (``±HH`` offsets, UTC-
normalized on parse) and ``texte_commentaire`` (HTML-escaped; unescaped
and tag-stripped on parse). Sampled refuges carry 19–54 text comments.
Every envelope states the data license: **CC BY-SA 2.0 FR**.

- **Hut linkage**: the existing `HutSource` (org `refuges`, fed by the
  hut import pipeline) provides the point id — zero new matching.
- **Serving**: comments merge into the hut listing (newest-first across
  both sources) as reviews with `rating: null`, synthetic signatures
  `refuges-info:{comment id}`, and **per-review attribution fields**
  (`source: "refuges.info"`, `license: "CC BY-SA 2.0 FR"`, `link` to
  the refuge page) — Mangrove items carry their own
  (`source: "mangrove"`, `license: "CC-BY-4.0"`). Summaries/aggregates
  are computed over the merged list (ratings only exist on Mangrove
  items).
- **Boundaries**: READ-ONLY. CC BY-SA content is never re-published into
  Mangrove (no relicensing to CC-BY-4.0; MaReSt reviews must be signed
  by their authors). Failures degrade to an empty provider list — the
  Mangrove listing never 503s because the secondary source is down.
  The signature blacklist hides provider comments too. Kill-switch:
  `ORA_REFUGES_INFO_ENABLED`.
- **Cache**: provider results cached per point id (15 min, like lists).

**Future read sources (researched 2026-11-08, none in scope):**
Camptocamp has no hut ratings (hut objects carry editorial `quality`
only) — its outings (`GET /outings?wtyp=hut&w={id}`) are trip reports,
a different product surface; Foursquare OS Places excludes reviews from
the open set; **Mapy.com** (Seznam) has reviews on the site but NO
public reviews API (map/geocode/route/panorama only) and user photos
are licensed to Seznam alone — community guidance explicitly forbids
reuse outside Mapy.com; **Google/TripAdvisor/Booking** are display-only
via official APIs (Google: Places-API display with author credit and
review links, no storage — only place IDs may be stored) or
partner-gated; deep links to their place pages are always fine. None of
these may be merged into our API responses.

### D12 — Replies, merge requests, moderation, history (round 2)

- **Replies** = ordinary signed Mangrove reviews whose subject is the
  parent review: `sub = urn:maresi:{signature}` with an optional
  helpfulness `rating` (MaReSt's "rate a review") and the reply text as
  `opinion`. `POST /v1/huts/{slug}/reviews/{signature}/reply`
  (authenticated, submit-quota). They do NOT appear in the hut's geo
  listing (their subject is a maresi URI, not geo) — the public
  `GET …/{signature}/replies` endpoint serves them (upstream
  `GET /reviews?sub=urn:maresi:…`, cached per signature; invalidated on
  new replies; blacklist applies).
- **Merge requests**: `POST /v1/huts/{slug}/reviews/merge-request`
  (authenticated, target + note + link) files a `ReviewMergeRequest`
  row — a staff queue (Unfold, state new/done/rejected). No automatic
  equivalence filing (zero-credibility keys do not resolve — §0 spike);
  an admin performs the actual merge/equivalence work manually.
- **Admin delete**: the blacklist IS the delete (a local serving
  decision — upstream deletion is impossible without the author's key;
  Wodore-authored reviews go through the erasure command). Bulk-paste
  admin action plus provider-id coverage from D11.
- **Edit history** (owner question): YES, two layers. Upstream stores
  BOTH the original and every edit (`latest_edits_only=false` returns
  the full chain, edit rows carrying `original_sub`) — history is
  retrievable for ANY review on demand. Locally, the append-only
  `SubmittedReview` log records every JWT Wodore signed (originals and
  edit actions) — history for our own users without upstream calls.
  Not exposed via an endpoint in this round; documented as a follow-up
  task.

## Risks / Trade-offs

- [Upstream API is 0.4.1, not frozen — breaking drift] → contract fixtures
  + pydantic pins fail CI early; defensive parsing maps drift to
  `service_unavailable`, never a 500; client adapter is one module.
- [Upstream outage] → reads serve within-TTL cache, then 503; writes 503
  (honest — reviews are not booking-critical); pending rows reconcile later.
- [Wodore holds users' private keys — custody liability] → encrypted at
  rest with a dedicated rotatable secret (MultiFernet: add-new-keep-old),
  export arrives in phase 2, erasure is a v1 command; document in ToS.
- [Loss of encryption secret = keys unrecoverable (users lose edit/delete
  of past reviews)] → MultiFernet old-key retention + Infisical secret
  history; accept and document (the upstream dataset itself is public and
  unaffected).
- [Slug-based subjects isolate us from MapComplete stock] → accepted
  (stock = 0, verified at dataset scale); equivalence claims by a
  credible key are the designated bridge (D7).
- [Slug edits fork the subject] → an editor changing a hut's slug (rare,
  manual) orphans the old subject's reviews. Mitigations: keep the old
  subject's reviews visible via the (future) equivalence bridge; document
  the hazard next to the slug field; a relocation/renumber admin action
  files equivalence claims once credible-key bridging is real.
- [Hut location edits] → moves under 2·u (60 m) still match (radius-sum
  rule — verified); larger moves orphan like slug edits (same mitigation).
- [Quota/gaming: accounts are free] → auth gate + per-user quota +
  upstream credibility does the heavy lifting; blacklist hides locally;
  revisit with heuristics only if abuse is observed.
- [OSM linkage coverage is partial (73%)] → unlinked huts submit without
  `metadata.osm_id`; coverage improves with the import pipeline's own
  refresh cadence — no reviews-path dependency on it.
- [PII leakage into an open dataset] → nickname-only policy (minted
  defaults), `extra="forbid"` DTO allowlist, no email/real-name fields
  accepted, documented in the submit endpoint description.
- [Amplification: anonymous reads fan out to the upstream] → dmr rate
  throttles on reads/batch (per-IP burst + daily), bounded batch (≤50),
  per-subject cache reuse.

## Migration Plan

Purely additive: new app + tables (no changes to existing tables; PROTECT
FKs only), new endpoints, env secrets. Rollout: deploy backend → seed
nothing (subjects are computed from hut rows) → frontend later. Rollback:
`ORA_ENABLED=false` (writes 503, reads degrade to empty) or revert
the deploy — no data migration involved. Fixture recapture and erasure
are ops-run commands, not deploy steps.

## Open decisions

- **O1 — `u` radius policy.** *Recommendation*: constant `u=30` for v1;
  per-hut extent later if the import pipeline ever captures element
  extents. (With slug `q`s, a larger `u` only widens *incoming* match
  tolerance from foreign subjects with the same normalized `q` — moot
  today.)
- **O2 — Equivalence bridging campaign.** Resolved as "not in v1" by the
  §0 spike (zero-credibility keys don't resolve); revisit once Wodore's
  reviewer identity has review volume (credibility) — file slug ≡
  OSM-name claims deliberately, hut by hut.
- **O3 — ETag interplay on hut endpoints.** *Recommendation* (adopted):
  hut endpoints stay review-blind; review volatility lives on separate,
  short-TTL endpoints. Revisit only if product wants summary chips
  embedded in hut detail.
- **O4 — Image hosting.** Adopted for v1: relay client URLs (upstream
  persists to `files.mangrove.reviews`, allowlisted at serving);
  Wodore-side upload via the `images` app stays a future option (DTO
  unchanged either way).
- **O5 — Exact endpoint/DTO shapes.** Finalized in D3 (one operation per
  path, `/v1/my/` namespace, batch as GET); field-level tweaks during
  implementation remain additive.
- **O6 — Rating ↔ stars mapping.** API stays integer 0–100 (any int —
  not star quanta); the frontend maps 5 stars ↔ 0/25/50/75/100 (MaReSt's
  own suggestion) and documents it in the UI.
- **O7 — Quota defaults.** Adopted: 5 submissions/day, 20 edit+delete/day
  (combined), reports rate-throttled not quota-counted; settings-tunable,
  start strict, loosen with data.
- **O8 — Timeouts, TTLs, throttles.** *Recommendation*: connect 5 s /
  read 10 s, 2 retries (GETs only); TTL 5 min lists / 15 min summaries /
  batch reuses summary cache; read throttle 60/min + 10 000/day per IP,
  batch 30/min. Tune with Sentry trace data.
