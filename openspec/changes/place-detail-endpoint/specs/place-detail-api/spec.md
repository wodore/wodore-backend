# Spec Delta: place-detail-api

## ADDED Requirements

### Requirement: Unified place detail endpoint
The system SHALL expose `GET /v1/geo/places/{place_id}` returning the
bare place resource (no envelope key) for every active, public
GeoPlace regardless of `detail_type` (amenity, transport, admin,
natural, none) — places without a detail model are first-class. The
response SHALL carry the base fields `id`, `slug`, `name`
(localized per `lang`), `country_code`, `elevation`, `importance`,
`location`, `description`, `detail_type` and `review_status`. The
endpoint SHALL accept the shared `lang` and `fields[TYPE]` query
parameters and SHALL NOT accept type or category filter parameters —
type filtering belongs to the list endpoints (`search`, `nearby`).
The route SHALL set `name=` equal to its operation id (`get_place`)
per `api-conventions`, and the change SHALL be registered as additive
(`api:added` label) per the `api-changelog` capability.

#### Scenario: Amenity place returns its detail block

- **WHEN** a client fetches an active, public amenity place by id
- **THEN** the response is the bare place object with
  `detail_type="amenity"` and, when a detail row exists, the
  `amenity_detail` member

#### Scenario: Place without a detail model is first-class

- **WHEN** a client fetches an active, public place of `detail_type`
  `natural` (or `admin`, `transport`, `none`) that has no exposed
  detail block
- **THEN** the response is 200 with the base fields and
  `detail_type` reporting the place's type, and no detail block member
  is fabricated

#### Scenario: No type filter parameters

- **WHEN** a client sends `?types=peak` or `?categories=terrain` to
  the detail endpoint
- **THEN** the parameters are ignored per the shared query-model
  extras policy — filtering lives on `places/search` and
  `places/nearby` only

### Requirement: Path keyed by stable numeric place id
The `{place_id}` path parameter SHALL be the GeoPlace primary key
matched by an integer path converter, and resolution SHALL filter to
`is_active=True` and `is_public=True`. Unknown, inactive or non-public
ids SHALL answer 404 with the single error contract body
(`{"code": "not_found", "detail": …}` plus the RFC 9457 members
`type`, `title`, `status` and `instance`) with no distinction between
the cases. The response SHALL include the place's `slug` so clients
can construct `place/{slug}` frontend URLs without a second
lookup.

#### Scenario: Unknown id answers the standard 404

- **WHEN** a client fetches an id that does not exist
- **THEN** the response is 404 with `code="not_found"` and the RFC
  9457 members, `instance` identifying the requested path

#### Scenario: Non-public place is indistinguishable from missing

- **WHEN** a client fetches the id of an inactive or non-public place
- **THEN** the response is the same 404 body as for an unknown id —
  the endpoint is no existence oracle

#### Scenario: slug rides along for URL building

- **WHEN** any place is fetched
- **THEN** the response carries its (unique, never-null) `slug`, and
  `place/{slug}` frontend URLs can be built from the detail response
  alone

### Requirement: Place slug invariant
Every GeoPlace row SHALL have a unique, non-null slug, enforced at
the database level (`null=False`). Input forms SHALL still accept an
empty slug because `save()` mints one at creation, and import/creation
paths SHALL mint the slug exactly once and never rewrite it for an
existing row.

#### Scenario: NOT NULL migration holds

- **WHEN** the slug cleanup migration runs against production data
- **THEN** it succeeds (no NULL slugs exist — the field's introducing
  migration backfilled every row) and subsequent inserts without a
  slug are rejected by the database

#### Scenario: Fallback slug for nameless places

- **WHEN** a place is created with an empty name and a category
- **THEN** `save()` mints a fallback slug from the category slug (or
  the `place-…` base without one), so no public place is ever served
  without a slug

### Requirement: Optional members under sparse fieldset selection
Optional response members SHALL follow the `fields[places]`
sparse-fieldset selection: `categories`, `sources`, `amenity_detail`
and `parties` (per the `geoplace-parties` capability). Without a
selection the response SHALL include every member that has data; with
a selection only the selected (plus required) members SHALL be
returned, with nested narrowing via `fields[parties]`,
`fields[categories]` and `fields[sources]` per the sparse-fieldsets
conventions. A detail block member SHALL be present only when the
place's `detail_type` matches the block and the detail row exists — blocks of other types SHALL NOT
be fabricated and requesting them SHALL NOT error. Database work for
unselected members SHALL be skipped (field-selected gating, the
search/nearby pattern). Future detail models (admin, transport,
natural) SHALL be exposed as sibling optional members — one per detail
model, added additively, following this same rule; no wrapper object
SHALL bundle the blocks.

#### Scenario: Default response includes everything present

- **WHEN** a client fetches an amenity place without a `fields`
  selection
- **THEN** the response carries every member that has data — base
  fields, `categories`, `sources`, `amenity_detail` and `parties`
  (when associations exist)

#### Scenario: Narrowed selection

- **WHEN** a client sends `?fields[places]=id,name,amenity_detail`
- **THEN** the response carries only `id`, `name` (plus the other
  required members) and `amenity_detail`, and category/source/party
  queries are not executed

#### Scenario: Block of another type is absent, not an error

- **WHEN** a client fetches a `natural` place with
  `?fields[places]=id,name,amenity_detail`
- **THEN** the response is 200 with the requested members and no
  `amenity_detail` member — the place's own type governs which blocks
  can exist

#### Scenario: Unknown block names 400 per the allowlist

- **WHEN** a client sends `?fields[places]=admin_detail` before an
  admin block change has landed
- **THEN** the response is 400 `invalid_field_name` naming the valid
  field names, per the sparse-fieldsets conventions

### Requirement: Deprecated amenity path alias
The system SHALL keep `GET /v1/geo/places/amenity/{place_id}`
(operation `get_amenity`) as a deprecated alias delegating to the
unified implementation. The alias SHALL scope resolution to
`detail_type="amenity"` — non-amenity ids answer 404 as before —
SHALL return the unified response body for amenity places (a superset
of the former `AmenitySchema`), and SHALL be marked deprecated in the
OpenAPI operation description pointing to `get_place`. Removing the
alias SHALL happen only via an `api:breaking` version bump per the
`api-versioning` runbook (registry `VersionChange`, committed
snapshot, sunset dates) — never as part of an additive change.

#### Scenario: Alias parity for amenity places

- **WHEN** a client fetches an amenity place via the alias path
- **THEN** the response body equals the `get_place` response for the
  same id (same members, same cache headers), and the operation is
  documented as deprecated

#### Scenario: Non-amenity 404 semantics preserved

- **WHEN** a client fetches the id of an active, public `natural`
  place via the alias path
- **THEN** the response is 404 — the alias addresses "the amenity at
  this id"; the unified route serves the same place with 200

#### Scenario: Retirement requires a version

- **WHEN** a future change removes the alias route
- **THEN** it registers an `api:breaking` `VersionChange` with a
  committed snapshot and deprecation/sunset dates per the versioning
  runbook

### Requirement: Caching parity with the places family
Both the unified route and the alias SHALL be served with
`Cache-Control: public, max-age=60` and server-side response caching
(`cache_page(60)`), matching the `places/search` and `places/nearby`
endpoints. Language and sparse-fieldset variants SHALL cache as
distinct variants (the cache keys on the full request URL).

#### Scenario: Cache headers match the family tier

- **WHEN** a client fetches a place detail on either route
- **THEN** the response carries `Cache-Control: public, max-age=60`

#### Scenario: Language variants cache separately

- **WHEN** the same place is fetched with `?lang=de` and `?lang=fr`
- **THEN** both variants are served correctly from the cache —
  cached responses are never mixed across query variants
