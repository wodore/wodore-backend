## ADDED Requirements

### Requirement: Collection envelope and bare singleton responses

Collection endpoints SHALL return a top-level JSON object keyed by the
resource name (e.g. `{"layers": [...]}`) and SHALL NOT return a bare
top-level JSON array. Singleton endpoints SHALL return the bare resource
object without a wrapping key. Endpoints created or meaningfully modified
after this change SHALL follow this rule; endpoints that predate it keep
their existing shapes until meaningfully modified.

#### Scenario: New collection endpoint returns an envelope

- **WHEN** a new endpoint returning multiple resources of type `widgets` is
  created after this change
- **THEN** the success response is a JSON object whose top-level `widgets`
  member is the array of resources, not a bare top-level array

#### Scenario: Singleton endpoint returns the bare resource

- **WHEN** a client fetches a single resource by its slug (e.g. a hut detail
  or a resolved map style document)
- **THEN** the response body is the resource object itself, with no
  `{"resource": …}` wrapper key

### Requirement: Single error contract

API errors SHALL use the uniform body `{"code": "<ErrorCode>", "detail":
"…"}` — `code` a machine-readable value from the shared `ErrorCode` enum
(one per HTTP behavioral class), `detail` the human-readable specific reason
— raised via `APIError(...)` / `raise_not_found(...)`, including plain
(non-dmr) views. Endpoints SHALL NOT introduce parallel error shapes.

#### Scenario: Missing resource

- **WHEN** a client requests a slug that does not exist and the handler calls
  `raise_not_found(...)`
- **THEN** the response status is 404 and the body is `{"code": "not_found",
  "detail": …}` in the shared error shape

#### Scenario: Invalid query parameter

- **WHEN** a client sends an unknown sparse-fieldset name or type bracket
- **THEN** the response status is 400 with the shared error shape and the
  `detail` names the valid values

### Requirement: Slug identifiers and ISO modified timestamps

Public identifiers in API payloads SHALL be stable, human-readable slugs;
database primary keys SHALL NOT be exposed. Content versions/timestamps SHALL
be ISO 8601 UTC values derived from the model's `modified` field, and a field
that IS the row's modified timestamp SHALL be named `modified` (not
`version`), so clients can key caches uniformly.

#### Scenario: Resource addressed by slug

- **WHEN** a client fetches or links a single resource
- **THEN** it is addressed by slug in the path (e.g. `/v1/map/styles/{slug}.json`),
  and the payload identifies it by slug with no numeric PK in the response

#### Scenario: Content version field

- **WHEN** a payload exposes the row's last-modified timestamp for client
  caching
- **THEN** the field is named `modified` and carries an ISO 8601 UTC string

### Requirement: Standard query parameters

Endpoints with narrowing SHALL compose the shared query models: `lang`
(`LanguageQuery`) for language selection and `fields[TYPE]=name1,name2`
(`SparseFieldsQuery` factory) for positive, allowlist-validated sparse
fieldsets (unknown names/types → 400 naming valid values; `__all__` opt-in).
Filter parameters SHALL be named after lowercase resource attributes, and
optional boolean filters SHALL default to unfiltered when omission must keep
hidden-but-needed rows resolvable. Where the backend owns selection policy,
the client states intent and the response SHALL report the value actually
served.

#### Scenario: Language and sparse fieldset composition

- **WHEN** a client sends `?lang=fr&fields[huts]=slug,name`
- **THEN** localized text fields are French and the response carries only the
  selected (plus required) fields

#### Scenario: Server-side selection reports the served value

- **WHEN** a client requests `?spec=medium` and only a `high` variant exists
- **THEN** the backend serves the `high` variant and the response reports the
  served spec (header and/or payload metadata), so fallback is observable

#### Scenario: Optional boolean filter defaults to unfiltered

- **WHEN** an optional visibility filter is omitted on an endpoint whose
  fallback chains may need hidden rows
- **THEN** the response includes those hidden-but-needed rows rather than
  filtering them out by default

### Requirement: Caching tiers

Evolving documents that must track database edits (catalogs, indexes) SHALL
be served with an ETag and revalidate-always caching (`Cache-Control:
public, max-age=0, must-revalidate, stale-if-error=604800`) — they SHALL NOT
use `stale-while-revalidate` and SHALL NOT be served through time-based
caching (`cache_page`) that can return pre-edit data within the window.
Immutable media (or redirects to content-unique URLs) MAY use long `max-age`
with `stale-while-revalidate`. ETag inputs SHALL cover everything that
changes the body: content version, `lang`, selection parameters, sparse
fieldsets, and the resolved API version.

#### Scenario: Edit visible on reload for evolving documents

- **WHEN** an editor changes a row serialized into an evolving document and a
  client reloads while online
- **THEN** the reload revalidates (ETag changed) and receives the edited
  content — no second reload needed and no stale window

#### Scenario: Immutable media may serve briefly stale

- **WHEN** a media redirect targets a content-unique filename and the
  underlying media is replaced
- **THEN** caches may keep the old redirect for its `max-age` window and
  serve it stale-while-revalidating, because the replacement changes the
  target URL

#### Scenario: ETag separates language variants

- **WHEN** the same evolving document is requested with `?lang=de` and
  `?lang=fr`
- **THEN** the two responses carry different ETags so a stored revalidation
  cannot mix languages

### Requirement: API versioning integration

Guideline-compliant changes SHALL classify against the date-based API
versioning runbook: additive changes need no new version; reshaping a
grandfathered endpoint to comply is breaking and SHALL follow the runbook
(fold into the unreleased version if one exists, otherwise create one, with
downgrade transforms and a committed snapshot). Every route SHALL set
`name=` on `dmr.routing.path` equal to its `@modify(operation_id=…)` value.

#### Scenario: New compliant endpoint is additive

- **WHEN** a new endpoint following these guidelines is added without
  changing existing endpoints
- **THEN** no new API version is created and the snapshot gains the endpoint

#### Scenario: Making a grandfathered endpoint compliant is breaking

- **WHEN** an existing bare-array collection endpoint is migrated to the
  envelope shape
- **THEN** the change follows the versioning runbook for breaking changes
  (VersionChange with downgrade transforms keyed by operation id, committed
  snapshot, `api:breaking` label)
