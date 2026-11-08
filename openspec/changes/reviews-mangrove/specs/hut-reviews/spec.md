## ADDED Requirements

### Requirement: Public review list per hut
The system SHALL serve `GET /v1/huts/{slug}/reviews` returning the reviews
of the hut's Mangrove subject in the generic collection envelope
(`{"data": […], "count": N}`), anonymously readable, newest-first
(action-edited reviews appearing with their latest edit), paginated, and
accepting `lang` like other hut endpoints. Huts that are not public or not
active SHALL answer 404. Huts whose subject has no reviews SHALL return an
empty collection, not an error. Every listed review SHALL carry at least
its `rating` (if present), `opinion` (if present), `nickname` (if present),
`language` (if present), `images`, flags (`is_affiliated`,
`is_personal_experience`), issuance time and its Mangrove `signature`, plus
the envelope `license` (`CC-BY-4.0`) and attribution link to the Mangrove
dataset.

#### Scenario: Anonymous read works

- **WHEN** an unauthenticated client requests `/v1/huts/{slug}/reviews` for a public active hut whose subject has reviews upstream
- **THEN** the response is 200 with the review collection, `license: "CC-BY-4.0"` and an attribution link

#### Scenario: Hut without reviews

- **WHEN** the hut's Mangrove subject has no reviews upstream
- **THEN** the response is 200 with `data: []` and `count: 0`

#### Scenario: Non-public hut hides

- **WHEN** the slug resolves to a hut that is not public or not active (or does not exist)
- **THEN** the endpoint answers 404 with the standard error contract

#### Scenario: Blacklisted reviews are excluded

- **WHEN** a review's signature is on the local blacklist
- **THEN** it is absent from the list and the count reflects the exclusion

### Requirement: Review summaries and map-badge batch aggregates
The system SHALL serve `GET /v1/huts/{slug}/reviews/summary` (per-hut
aggregate: review count, mean rating, positives when upstream provides
them) and a batch summary endpoint accepting a bounded list of hut slugs
and returning one aggregate per hut (fed by the upstream batch/subject
aggregate calls). Zero-review huts SHALL return zeroed aggregates. Both
SHALL be anonymously readable and cacheable like the review list.

#### Scenario: Single-hut summary

- **WHEN** a public hut's subject has 3 reviews with ratings 25/50/100 upstream
- **THEN** the summary reports count 3 and the mean of the ratings

#### Scenario: Batch for map badges

- **WHEN** the batch summary endpoint receives a list of hut slugs within its bound
- **THEN** it returns one aggregate per requested slug (zeroed for huts without reviews) and rejects oversized lists with a validation error

### Requirement: Authenticated review submission
The system SHALL serve `POST /v1/huts/{slug}/reviews` requiring
`AuthBearer` authentication. The request body SHALL accept `rating`
(integer 0–100) and/or `opinion` (≤1000 chars), optional `images`
(≤5 items of `{src: https URL, label?: ≤50 chars}`) and an optional
metadata subset (`nickname`, `language`, `experience_context`,
`is_personal_experience`, `is_affiliated`). The backend SHALL validate the
payload against the Mangrove Review Standard, reject unknown metadata keys
(`400` with `review_invalid_*` error codes), enrich it server-side
(`client_id`, `license: CC-BY-4.0`, `osm_id` from the hut's OSM linkage
when present, language defaulting from the request), sign it with the
account's reviewer key and relay it upstream. A successful submission
SHALL return the created review including its `signature`, invalidate the
hut's cached list/summary, and be recorded in the local submission log.

#### Scenario: Successful submission

- **WHEN** an authenticated user posts `{rating: 75, opinion: "…"}` for a public hut and the upstream accepts the signed JWT
- **THEN** the response is 201 with the review (including its `signature`), and a subsequent list request reflects the new review without waiting for cache TTL

#### Scenario: Anonymous submission refused

- **WHEN** an unauthenticated client posts a review
- **THEN** the response is 401 with the standard `not_authenticated` error body

#### Scenario: Out-of-range rating

- **WHEN** the body carries `rating: 120` or an unknown metadata key
- **THEN** the response is 400 with a `review_invalid_*` error code and nothing is signed or relayed

#### Scenario: Upstream rejection surfaces sanitized

- **WHEN** the upstream server rejects the signed JWT (4xx)
- **THEN** the response carries a review submission error code with a sanitized detail; the raw upstream body is logged server-side only

### Requirement: Per-user write quota
The system SHALL enforce a configurable per-user rolling-window quota on
review write actions (submissions, edits, deletes — configurable per
action class, defaults set by settings). Exceeding the quota SHALL answer
429 with error code `review_quota_exceeded` and the reset time, without
signing or relaying anything. Authenticated requests below the quota SHALL
be unaffected by any anonymous-user throttles beyond the ordinary rate
throttles.

#### Scenario: Quota exhaustion

- **WHEN** a user submits more reviews within the window than the configured submission quota
- **THEN** the next submission answers 429 with `review_quota_exceeded` and a reset time

#### Scenario: Window rolls over

- **WHEN** the window passes after exhaustion
- **THEN** the user can submit again without any manual intervention

### Requirement: Review edit with signed action
The system SHALL serve `PATCH /v1/huts/{slug}/reviews/{signature}`
requiring authentication. It SHALL accept updated `rating` and/or
`opinion` (same validation as submission), verify locally that the target
review's key id belongs to the caller's account, then sign an
`action: "edit"` JWT against `urn:maresi:{signature}` and relay it
upstream. A successful edit SHALL invalidate the hut's caches and return
the updated review state. Non-owned targets SHALL answer 403 without
signing.

#### Scenario: Owner edits

- **WHEN** the caller's reviewer key is the key that signed the target review and the upstream accepts the edit action
- **THEN** the response reflects the updated rating/opinion and subsequent list requests serve the latest edit

#### Scenario: Non-owner refused

- **WHEN** the target review was signed by a different key than the caller's
- **THEN** the response is 403, and no JWT is signed or relayed

### Requirement: Review delete with signed action
The system SHALL serve `DELETE /v1/huts/{slug}/reviews/{signature}`
requiring authentication and local ownership (same rule as edit), then
sign an `action: "delete"` JWT against `urn:maresi:{signature}` and relay
it. Success SHALL return 204, remove the review from the local submission
log's active set, and invalidate the hut's caches.

#### Scenario: Owner deletes

- **WHEN** the owner deletes their review and the upstream accepts the action
- **THEN** the endpoint answers 204 and the review disappears from Wodore-served lists once the upstream marks it deleted

### Requirement: Abuse report relay
The system SHALL serve `POST /v1/huts/{slug}/reviews/{signature}/report`
requiring authentication with a reason text (`opinion` ≤1000), sign an
`action: "report_abuse"` JWT (no rating) with the *reporter's* key against
`urn:maresi:{signature}`, and relay it upstream. Reporting SHALL NOT
require ownership of the target review.

#### Scenario: Any user reports

- **WHEN** any authenticated user reports a foreign review with a reason
- **THEN** the signed `report_abuse` action is relayed and the endpoint answers 2xx

### Requirement: My reviews listing
The system SHALL serve `GET /v1/me/reviews` requiring authentication,
returning the reviews authored by the caller's reviewer key (upstream
kid-listing), each annotated with the Wodore hut slug resolved from its
subject URI and the review's state (deleted reviews excluded, edited
reviews shown with their latest edit). Subjects that do not resolve to a
Wodore hut (e.g. reviews imported with an external identity) SHALL be
listed with the hut annotation absent rather than dropped.

#### Scenario: Own reviews with hut context

- **WHEN** the caller has submitted reviews on two huts
- **THEN** the listing contains both reviews, each carrying the respective hut slug

#### Scenario: Imported identity reviews appear

- **WHEN** the caller imported a key that had written reviews on non-Wodore subjects
- **THEN** those reviews are listed without a hut slug annotation

### Requirement: Signature blacklist moderation
The system SHALL keep an admin-managed blacklist of Mangrove review
signatures (with reason and author). Blacklisted signatures SHALL be
excluded from all Wodore-served review lists, summaries and batch
aggregates. Blacklisting SHALL be a local serving decision that never
mutates or deletes upstream data.

#### Scenario: Blacklist hides a review

- **WHEN** staff blacklists a review's signature via the admin
- **THEN** list and aggregate responses exclude it from that moment on, upstream data unchanged

### Requirement: Caching, CDN and versioning behavior
Review read endpoints SHALL set cache headers (`Cache-Control` with
bounded max-age) and the CDN tag `api:reviews`; write endpoints SHALL be
`no-store`. Successful local writes SHALL invalidate the affected hut's
list, summary and batch-aggregate cache entries (write-through), and purge
the CDN tag. All review endpoints SHALL pass through the API versioning
middleware (additive endpoints — no version transforms) and the shared
RFC 9457 error contract. Hut detail endpoints and their ETags SHALL NOT
change as a function of review state.

#### Scenario: Write-through invalidation

- **WHEN** a review is submitted for a hut whose list response is cached
- **THEN** the next list request re-fetches from upstream rather than serving the pre-write cache entry

#### Scenario: Hut ETags stay review-blind

- **WHEN** a review is added upstream for a hut
- **THEN** the hut detail endpoint's ETag and body are unchanged (reviews surface only via review endpoints)

#### Scenario: Upstream failure degrades gracefully

- **WHEN** the upstream API is unreachable or slow beyond the configured timeouts
- **THEN** read endpoints answer 503 `upstream_unavailable` (or serve within-TTL cache where applicable) — never a 5xx with an unsanitized upstream body or stack trace
