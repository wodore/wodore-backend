## ADDED Requirements

### Requirement: Deterministic hut subject construction
The system SHALL compute every hut's Open Reviews subject as a function of
the hut row and its **review name**: `geo:{lat},{lon}?q={name}&u={radius}`
with coordinates from `Hut.location` (WGS84, 6 decimals) and `u` one
configurable constant (default from settings). The review name SHALL
resolve as: the **pinned** name (`HutReviewSubject`, created when the
hut's first review is written) → the OSM name (current `HutSource`, org
`osm`) → the hut's own name. The same unchanged hut row plus an
unchanged pinned state SHALL always yield byte-identical subjects, and
the first review write on a hut SHALL pin the resolved name so later
renames cannot fork the subject. A check SHALL report huts within twice
the `u` radius whose resolved names normalize equal (shared-review
collision warning).

#### Scenario: Recipe stability

- **WHEN** the subject is computed twice for an unchanged hut with no pinned name change
- **THEN** both computations produce the identical URI string

#### Scenario: OSM name used before any review

- **WHEN** a hut has a current OSM HutSource and no pinned review name
- **THEN** the subject `q` is the OSM name (URL-encoded)

#### Scenario: First review pins the name

- **WHEN** the hut's first review is submitted
- **THEN** the resolved name at that moment is stored as the hut's pinned review name, and subsequent subjects use the pinned name even if the OSM or hut name later changes

#### Scenario: Collision warning

- **WHEN** two nearby huts (within twice the `u` radius) have review names that differ only by case or punctuation
- **THEN** the check reports the collision so operators can act before reviews are shared

### Requirement: Single upstream client
All communication with the Open Reviews API SHALL go through one client module
(`MangroveClient`) configured with the base URL from settings. It SHALL
enforce explicit connect and read timeouts on every request, retry only
idempotent GET requests with a bounded retry budget and backoff, and never
retry write submissions. Writes SHALL use `POST /submit` with the JWT as a
`text/plain` body (the deprecated `PUT /submit/{jwt}` path MUST NOT be
used — it would leak review content into URL logs). No other code path
SHALL issue requests to the Open Reviews API.

#### Scenario: Writes never retry

- **WHEN** a submit relay times out
- **THEN** the operation fails fast with the upstream-unavailable condition instead of re-submitting the same JWT

#### Scenario: Reads tolerate a blip

- **WHEN** a GET fails once with a transient network error
- **THEN** the client retries within its budget before surfacing the failure

### Requirement: Upstream contract pinning
The client's expected request and response shapes SHALL be pinned to
Mangrove Server API 0.4.1 (endpoints `GET /reviews`, `GET /geo`,
`GET /subject/{sub}`, `GET /issuer/{pem}`, `GET /review/{signature}`,
`POST /batch`, `POST /submit`, `GET /dump`, `GET /stats/clients`) via
recorded fixtures and typed response models. Fixtures SHALL be captured
against reserved test subjects only. Contract tests SHALL replay the
fixtures against the client so upstream drift fails CI. Runtime parsing
SHALL be defensive: unknown fields ignored; missing essential fields
degrade to the upstream-unavailable condition rather than an unhandled
error.

#### Scenario: Fixture replay gates CI

- **WHEN** the client's response models no longer match the recorded 0.4.1 fixtures
- **THEN** the contract tests fail

#### Scenario: Defensive parsing on drift

- **WHEN** the live upstream adds unknown fields or changes non-essential shape
- **THEN** serving degrades to a sanitized error or partial data, never an unhandled exception

### Requirement: Signed write relay with submission log
Review writes (submit, edit, delete, report_abuse) SHALL be constructed as
Open Reviews Standard (MaReSt) JWTs (`ES256`, header `kid` PEM + `jwk`,
MaReSt-compliant claims) and relayed via `POST /submit`. The review
signature SHALL be derived locally as the JWT's third base64url segment
(the upstream submission response carries none). Every write SHALL be
recorded in the local submission log: a row created in `pending` state
before the relay, then marked `accepted` or `failed` according to the
outcome. The log SHALL be append-only — a delete is a new action row, and
only the erasure path (review-identity) destroys rows. The log SHALL be
an audit/erasure/archival aid and SHALL NOT be a serving path — reads go
upstream (via cache) regardless of the log's contents.

#### Scenario: Log records the derived signature

- **WHEN** the upstream accepts a submitted review
- **THEN** the log row is marked accepted and stores the JWT together with its derived signature

#### Scenario: Failed relays stay honest

- **WHEN** a relay fails upstream
- **THEN** the row is marked failed (never silently dropped), so quota counting and reconciliation see the attempt

#### Scenario: Reads do not depend on the log

- **WHEN** the submission log is empty (fresh install, cache cold)
- **THEN** review lists still serve correctly from the upstream API

### Requirement: Upstream error translation
Upstream failures (timeout, connection error, 5xx, unparsable body) SHALL
map to one internal condition surfaced as `503` with the registered
`service_unavailable` error body. Raw upstream bodies and URLs SHALL NOT
be included in client-facing error details; they SHALL be logged
server-side for diagnosis.

#### Scenario: Sanitized failure surface

- **WHEN** the upstream answers 500 with an HTML body
- **THEN** the API client receives `service_unavailable` with the standard error body, and the raw body appears only in server logs

### Requirement: Observability without review PII
Every upstream call SHALL emit a structlog event and be traced to Sentry
(spans/breadcrumbs). Opinion texts and nicknames SHALL NOT be logged at
info level (they can flow into breadcrumbs/error events); request-level
logging SHALL carry subjects, endpoints, statuses and durations only.

#### Scenario: Submit logging without opinion text

- **WHEN** a review submission is relayed
- **THEN** the log event names the subject, action and result but does not contain the opinion or nickname

### Requirement: Open-data archival and sovereignty
The system SHALL document that the upstream dataset is canonical and open
(CC-BY-4.0; a full-dataset dump is published daily via `GET /dump`), that
local review reads always proxy it, and SHALL provide an export of the
local submission log (verbatim JWTs — independently verifiable) sufficient
to reconstruct Wodore-authored review authorship independently of upstream
availability.

#### Scenario: Submission log export

- **WHEN** an operator exports the submission log
- **THEN** the export contains verbatim JWTs whose signatures verify against their embedded public keys without any Wodore service involved
