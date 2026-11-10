# hut-reviews Specification

## Purpose
TBD - created by archiving change reviews-mangrove. Update Purpose after archive.
## Requirements
### Requirement: Public review list per hut
The system SHALL serve `GET /v1/huts/{slug}/reviews` returning the reviews
of the hut's Open Reviews subject in the generic collection envelope
(`{"data": […], "count": N}`), anonymously readable, newest-first (upstream
`latest_edits_only` already collapses edits), locally paginated
(`limit` ≤100 default 20, `offset`). Huts that are not public or not
active SHALL answer 404. Huts whose subject has no reviews SHALL return an
empty collection, not an error. Every listed review SHALL carry at least
its `rating` (if present), `opinion` (if present), `nickname` (if present),
`language` (if present), images (allowlist-filtered), flags
(`is_affiliated`, `is_personal_experience`), issuance time, its
`signature`, and per-review attribution: `source` (`mangrove` or the
provider id), `license` (the review content's license) and `link` (the
source page, when one exists); the envelope SHALL carry `license:
"CC-BY-4.0"` and an attribution link to the Open Reviews dataset. The
listing SHALL merge reviews from read-only providers (spec:
open-reviews-client D11 — refuges.info comments, per-review
`source`/`license`/`link`), newest-first across all sources.

#### Scenario: Anonymous read works

- **WHEN** an unauthenticated client requests `/v1/huts/{slug}/reviews` for a public active hut whose subject has reviews upstream
- **THEN** the response is 200 with the review collection, `license: "CC-BY-4.0"` and an attribution link

#### Scenario: Hut without reviews

- **WHEN** the hut's Open Reviews subject has no reviews upstream
- **THEN** the response is 200 with `data: []` and `count: 0`

#### Scenario: Non-public hut hides

- **WHEN** the slug resolves to a hut that is not public or not active (or does not exist)
- **THEN** the endpoint answers 404 with the standard error contract

#### Scenario: Blacklisted reviews are excluded

- **WHEN** a review's signature is on the local blacklist
- **THEN** it is absent from the list and the count reflects the exclusion

#### Scenario: Provider comments merge with attribution

- **WHEN** the hut has a refuges.info HutSource with comments
- **THEN** those comments appear in the listing carrying `source: "refuges.info"`, the CC BY-SA 2.0 FR license label and a link to the refuge page, merged newest-first with the Open Reviews reviews

#### Scenario: Provider outage degrades to Mangrove only

- **WHEN** the refuges.info API fails
- **THEN** the listing still serves Open Reviews reviews (provider items absent, no error)

#### Scenario: Foreign subjects do not leak in

- **WHEN** upstream returns (e.g. via an equivalence link) a review whose subject does not match the hut's subject under the geo rule — normalized `q` equality and coordinates within the sum of both `u` radii
- **THEN** that review is dropped from the listing

### Requirement: Locally computed summaries and map-badge batches
The system SHALL serve `GET /v1/huts/{slug}/reviews/summary` and
`GET /v1/reviews/summary?slugs=…` (≤50 slugs, deduplicated and
canonicalized before cache-keying), both anonymously readable and
cacheable like the review list. Aggregates SHALL be computed locally from
the cached, blacklist-filtered review list: `count` (listed reviews),
`rating_count` and `rating_mean` (over rated reviews only),
`positive_count` (rating > 50), `opinion_count`. Zero-review huts SHALL
return zeroed aggregates; oversized slug lists SHALL answer 400 with the
standard validation error.

#### Scenario: Single-hut summary

- **WHEN** a public hut's visible reviews carry ratings 25/50/100 and one unrated opinion
- **THEN** the summary reports count 4, rating_count 3, rating_mean 58.3, positive_count 1, opinion_count 1

#### Scenario: Batch for map badges

- **WHEN** the batch endpoint receives 30 slugs within its bound
- **THEN** it returns one aggregate per slug (zeroed for huts without reviews), reusing the per-subject cached lists

#### Scenario: Oversized batch refused

- **WHEN** more than 50 slugs are requested
- **THEN** the response is 400 with the standard validation error code

### Requirement: Authenticated review submission
The system SHALL serve `POST /v1/huts/{slug}/reviews/submit` requiring
authentication. The request body SHALL accept `rating` (integer 0–100)
and/or `opinion` (≤1000 code points), optional `images` (≤5 items of
`{src: https URL, label?: ≤50 chars}`) and an optional metadata subset
(`nickname`, `language`, `experience_context`,
`is_personal_experience: true`, `is_affiliated: true`) — unknown keys are
rejected by the typed DTO with the standard validation error. The backend
SHALL enrich server-side (`client_id`, `license: CC-BY-4.0`, `osm_id`
from the hut's OSM linkage when present, nickname/language defaults),
sign the JWT with the account's reviewer key, relay it upstream, and
return 201 with the created review including its derived `signature`
(the JWT's third segment). A successful submission SHALL invalidate the
hut's cached list/summary and be recorded in the local submission log.

#### Scenario: Successful submission

- **WHEN** an authenticated user posts `{rating: 75, opinion: "…"}` for a public hut and the upstream accepts the signed JWT
- **THEN** the response is 201 with the review (including its `signature`), and a subsequent origin or authenticated list request reflects the new review immediately

#### Scenario: Anonymous submission refused

- **WHEN** an unauthenticated client submits a review
- **THEN** the response is 401 with the standard `not_authenticated` error body

#### Scenario: Out-of-range rating

- **WHEN** the body carries `rating: 120` or an unknown key
- **THEN** the response is 400 with the standard validation error and nothing is signed or relayed

#### Scenario: Upstream rejection surfaces sanitized

- **WHEN** the upstream server rejects the signed JWT (4xx)
- **THEN** the response is a sanitized error without the raw upstream body; the raw body is logged server-side only

### Requirement: Per-user write quota
The system SHALL enforce a rolling 24-hour per-user quota counted from
the submission-log rows: submissions (default 5/day) and edit+delete
combined (default 20/day), both configurable. Exceeding the quota SHALL
answer 429 with error code `review_quota_exceeded` (registered in the
shared RFC 9457 registry), a `Retry-After` header and the reset time in
the body, without signing or relaying anything. Abuse reports are not
quota-counted; they carry an ordinary rate throttle.

#### Scenario: Quota exhaustion

- **WHEN** a user submits more reviews within 24 hours than the configured submission quota
- **THEN** the next submission answers 429 with `review_quota_exceeded`, a `Retry-After` header and a reset time in the body

#### Scenario: Window rolls over

- **WHEN** 24 hours pass after exhaustion
- **THEN** the user can submit again without any manual intervention

### Requirement: Signed edit action
The system SHALL serve `POST /v1/huts/{slug}/reviews/{signature}/edit`
requiring authentication and local ownership of the target (its signature
in the submission log under the caller's user and key, or — for keys not
in the log — the upstream review record whose `kid` equals the caller's,
compared whitespace-insensitively). It SHALL accept updated `rating`
and/or `opinion` (same validation as submission), sign an
`action: "edit"` JWT against `urn:maresi:{signature}` and relay it. A
successful edit SHALL invalidate the hut's caches and return the updated
review state. Targets that belong to a different subject than the hut in
the path SHALL answer 404; non-owned targets SHALL answer 403 with
nothing signed.

#### Scenario: Owner edits

- **WHEN** the caller's reviewer key is the key that signed the target review and the upstream accepts the edit action
- **THEN** the response reflects the updated rating/opinion and subsequent list requests serve the latest edit

#### Scenario: Non-owner refused

- **WHEN** the target review was signed by a different key than the caller's
- **THEN** the response is 403, and no JWT is signed or relayed

#### Scenario: Foreign target hidden

- **WHEN** the signature in the path does not belong to the hut's subject
- **THEN** the response is 404, and no JWT is signed or relayed

### Requirement: Signed delete action
The system SHALL serve `POST /v1/huts/{slug}/reviews/{signature}/delete`
requiring authentication and local ownership (same rules as edit), then
sign an `action: "delete"` JWT against `urn:maresi:{signature}` and relay
it, treating an upstream refusal for an already-deleted target as
success (idempotent). Success SHALL return 204 and record a `delete` action
row in the submission log (append-only); the hut's next read drops the
deleted review via the own-write overlay.

#### Scenario: Owner deletes

- **WHEN** the owner deletes their review and the upstream accepts the action
- **THEN** the endpoint answers 204, a delete action row is appended to the log, and the review disappears from Wodore-served lists

#### Scenario: Delete is idempotent

- **WHEN** the upstream refuses the delete because the review is already deleted
- **THEN** the endpoint still answers 204 and the local caches are invalidated

### Requirement: Abuse report relay
The system SHALL serve
`POST /v1/huts/{slug}/reviews/{signature}/report` requiring
authentication and a required reason text (`opinion` ≤1000), sign an
`action: "report_abuse"` JWT (no rating) with the *reporter's* key
against `urn:maresi:{signature}`, and relay it upstream. Reporting SHALL
NOT require ownership of the target review; the target MUST belong to
the hut's subject (404 otherwise). The endpoint carries an ordinary rate
throttle.

#### Scenario: Any user reports

- **WHEN** any authenticated user reports a foreign review with a reason
- **THEN** the signed `report_abuse` action is relayed and the endpoint answers 2xx

#### Scenario: Reason is required

- **WHEN** a report is submitted without an opinion text
- **THEN** the response is 400 with the standard validation error

### Requirement: My reviews listing
The system SHALL serve `GET /v1/my/reviews` on the user-scoped `/v1/my/`
controller base (bearer/session authenticated, `private, no-store`,
never a CDN candidate), returning the reviews authored by the caller's
reviewer key (upstream `kid` listing), each annotated with the Wodore
hut slug resolved from its subject URI when it resolves to a public hut
(annotation absent otherwise). Deleted reviews SHALL be excluded and
edited reviews shown with their latest edit.

#### Scenario: Own reviews with hut context

- **WHEN** the caller has submitted reviews on two huts
- **THEN** the listing contains both reviews, each carrying the respective hut slug

#### Scenario: Foreign-subject reviews appear unannotated

- **WHEN** the caller's key has written reviews on non-Wodore subjects (e.g. after a future key import)
- **THEN** those reviews are listed without a hut slug annotation

### Requirement: Replies to reviews
The system SHALL serve `POST /v1/huts/{slug}/reviews/{signature}/reply`
requiring authentication with a body of `rating` (helpfulness, 0–100)
and/or `opinion` (≤1000), plus optional `images` (≤5 × `{src: https
URL, label?: ≤50}` — same validation as submissions). The reply SHALL be signed as an ordinary
Open Reviews review whose subject is `urn:maresi:{signature}`, counted
against the submission quota, and logged with the parent signature as
its target. The public `GET /v1/huts/{slug}/reviews/{signature}/replies`
SHALL list a parent review's replies (cached per signature, blacklist-
filtered, newest-first). Targets that do not belong to the hut in the
path SHALL answer 404.

#### Scenario: Reply relayed with maresi subject

- **WHEN** an authenticated user replies to a hut review with a text
- **THEN** the signed JWT's subject is `urn:maresi:{signature}` and the replies endpoint can serve it afterwards

#### Scenario: Replies require content

- **WHEN** a reply body carries neither rating nor opinion
- **THEN** the response is 400 with the standard validation error

#### Scenario: Replies may carry images

- **WHEN** a reply body carries an opinion and one https image URL
- **THEN** the signed reply JWT includes the images and the response echoes them

### Requirement: Review photos in the image gallery
The system SHALL expose the images attached to a hut's Open Reviews reviews
through the standard image-provider pipeline (the same gallery endpoint
and fan-out as the other providers): each review photo becomes a gallery
feature with the review's license (CC-BY-4.0 by default), the reviewer
nickname as author, Mangrove provider attribution, and imagor-served
display variants. Photos of blacklisted reviews SHALL be excluded;
provider failures SHALL degrade to an empty result; the
`ORA_ENABLED` kill-switch SHALL disable the source.

#### Scenario: Review photo appears in the hut gallery

- **WHEN** a hut has a visible Open Reviews review carrying an image on the allowlisted host
- **THEN** the hut's image gallery fan-out includes that photo with CC-BY-4.0 license, reviewer attribution and imagor display URLs

#### Scenario: Blacklisted review photo hidden

- **WHEN** the only review carrying a photo is blacklisted
- **THEN** the gallery does not include the photo

### Requirement: Reviewer profile endpoint
The system SHALL serve `GET /v1/my/reviews/profile` (authenticated)
returning the caller's reviewer profile defaults (`nickname`,
`language`), creating the profile with a minted nickname if none
exists. `PATCH /v1/my/reviews/profile` SHALL accept optional
`nickname` (≤50) and `language` (BCP 47 ≤35) updates. Profile changes
apply to future reviews only; existing reviews are unchanged.

#### Scenario: Read profile

- **WHEN** an authenticated user reads their profile
- **THEN** the response includes a non-empty nickname (minted if first access) and an optional language

#### Scenario: Update nickname

- **WHEN** the user patches their nickname
- **THEN** subsequent reviews carry the new nickname; existing reviews keep the old one

### Requirement: Review merge requests
The system SHALL serve
`POST /v1/huts/{slug}/reviews/merge-request` requiring authentication
with a body of `target` (subject URI, slug or URL, ≤255), optional
`note` and `link`. The request SHALL be stored in an admin-managed
staff queue (states new/done/rejected) — an operator performs the
actual subject merge/equivalence work manually; nothing is written to
Mangrove automatically.

#### Scenario: Merge request queued

- **WHEN** an authenticated user files a merge request with a target
- **THEN** it is stored as `new` and visible in the admin queue

#### Scenario: Target is required

- **WHEN** the body carries no target
- **THEN** the response is 400 with the standard validation error

### Requirement: Signature blacklist moderation
The system SHALL keep an admin-managed blacklist of Open Reviews review
signatures (with reason and author). Blacklisted signatures SHALL be
excluded from all Wodore-served review lists, summaries and batch
aggregates — covering both Mangrove signatures and read-only provider
ids. Blacklisting SHALL be a local serving decision that never mutates
or deletes upstream data.

#### Scenario: Blacklist hides a review

- **WHEN** staff blacklists a review's signature via the admin
- **THEN** list and aggregate responses exclude it from that moment on, upstream data unchanged

### Requirement: Caching and versioning behavior
Review read endpoints SHALL set bounded public cache headers (short
max-age); write endpoints and the my-reviews endpoint SHALL be
uncached/private. Local list/summary caches SHALL use a 15-minute TTL.
Successful local writes SHALL **merge write-through**: a submitted
review is prepended into the cached list, an edit updates the cached
copy and a delete removes it — so the author's own write is visible on
the next read even while upstream indexing lags or the TTL has not
expired. All review
endpoints SHALL pass through the API versioning middleware (additive
endpoints — no version transforms) and the shared RFC 9457 error
contract. Hut detail endpoints and their ETags SHALL NOT change as a
function of review state. Anonymous reads SHALL be rate-throttled and
the batch endpoint bounded (≤50 slugs).

#### Scenario: Own-write overlay

- **WHEN** a review is submitted for a hut and the upstream listing does not yet include it (indexing lag)
- **THEN** the hut's next read still shows it (prepended from the submission log), cold cache or not

#### Scenario: Deleted stays hidden under lag

- **WHEN** a review is deleted but the upstream listing still returns it
- **THEN** the hut's next read hides it (the delete action row drops it via the overlay)

#### Scenario: Hut ETags stay review-blind

- **WHEN** a review is added upstream for a hut
- **THEN** the hut detail endpoint's ETag and body are unchanged (reviews surface only via review endpoints)

#### Scenario: Upstream failure degrades gracefully

- **WHEN** the upstream API is unreachable or slow beyond the configured timeouts
- **THEN** read endpoints answer 503 with the registered `service_unavailable` error body while within-TTL cache still serves — never a 5xx with an unsanitized upstream body or stack trace

