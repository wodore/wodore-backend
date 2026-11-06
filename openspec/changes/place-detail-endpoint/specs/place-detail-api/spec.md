# Spec Delta: place-detail-api

## ADDED Requirements

### Requirement: Unified place detail endpoint
The system SHALL expose `GET /v1/geo/places/{slug}` returning the bare
place resource (no envelope key) for every active, public GeoPlace
regardless of `detail_type` (amenity, transport, admin, natural, none)
— places without a detail model are first-class. The response SHALL
carry the base fields `slug`, `name` (localized per `lang`),
`country_code`, `elevation`, `importance`, `location`, `description`,
`detail_type` and `review_status`. No `modified` timestamp is exposed
at this time — freshness is governed by the `Cache-Control: public,
max-age=60` tier (see Path resolution and caching parity); exposing
`modified` is revisited when ETag caching is adopted for the places
family. The endpoint SHALL accept the
shared `lang` and `fields[TYPE]` query parameters and SHALL NOT accept
type or category filter parameters — type filtering belongs to the
list endpoints (`search`, `nearby`). The route SHALL set `name=` equal
to its operation id (`get_place`) per `api-conventions`, and the
change SHALL be registered in the API changelog per the
`api-changelog` capability.

#### Scenario: Amenity place returns its detail block

- **WHEN** a client fetches an active, public amenity place by slug
- **THEN** the response is the bare place object with
  `detail_type="amenity"` and, when a detail row exists, the
  `amenity` member

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
- **THEN** the parameters are ignored silently (unrecognized query
  parameters are passed through without error) — filtering lives on
  `places/search` and `places/nearby` only

### Requirement: Slug-only identifiers in the places family
Places SHALL be identified by their unique slug in every
places-family response, and database primary keys SHALL NOT be
exposed: `places/search`, `places/nearby` and the detail route carry
`slug` as the required identifier member and no numeric `id`. The
transition SHALL be registered as a breaking change per the
`api-versioning` runbook — amended into the current unreleased
version (never stacked), with a regenerated committed snapshot and the
`api:breaking` label. The `places/amenity/{place_id}` route
(operation `get_amenity`) SHALL be removed in that same version with
no alias (pre-release surface, zero consumers), and the generated
frontend client SHALL be regenerated.

#### Scenario: List results navigate to detail by slug

- **WHEN** a client reads a `places/search` or `places/nearby`
  response and fetches one result
- **THEN** the item's `slug` member addresses
  `/v1/geo/places/{slug}`, and no numeric id appears in either
  response

#### Scenario: Removed amenity route

- **WHEN** a client requests `/v1/geo/places/amenity/{id}` after the
  breaking version ships
- **THEN** the route no longer exists (404 from the router), and the
  OpenAPI snapshot for the new version no longer lists `get_amenity`

#### Scenario: Breaking change registered per the runbook

- **WHEN** the PR is labeled `api:breaking`
- **THEN** the registry's unreleased `VersionChange` documents the
  identifier switch and the amenity removal, the committed snapshot
  matches the registry, and CI's release-state invariant passes

### Requirement: Slug grammar and routing safety
Item routes under `places/` SHALL be matched by a registered path
converter whose slug grammar — slug-charset characters containing at
least one hyphen or underscore — structurally excludes every fixed
collection segment, so URL resolution SHALL NOT depend on path
registration order. Fixed collection segments under `places/` SHALL
be single lowercase words without hyphens or underscores. The slug
grammar SHALL be enforced at the database level (a check constraint
on the slug column matching the converter regex, so every write path
— admin forms, imports, raw SQL — is covered, not only those calling
full model validation) and mirrored by model-layer `clean()`
validation with a reserved-name blacklist (`search`, `nearby`,
`overlays`, `meta`, `amenity`) for friendly admin errors. A one-time
migration SHALL re-mint any pre-existing violating slug before the
constraint is added. The slug-keyed SEO siblings (`places/{slug}/meta`,
`places/{slug}.md`) SHALL use the same converter.

#### Scenario: Fixed segment is never captured as a slug

- **WHEN** a client requests `/v1/geo/places/search` (or `nearby`,
  `overlays`) regardless of the order routes are registered in
- **THEN** the fixed collection endpoint answers, because the
  converter grammar cannot match a hyphen-less, underscore-less
  segment

#### Scenario: Item fetch works for every production slug

- **WHEN** a client fetches a place by any slug in the production
  data, including legacy shapes (`vending_machine`,
  `drinking_water-`, `information-5h9`)
- **THEN** the converter matches and the place resolves

#### Scenario: Manual slug violating the grammar is rejected

- **WHEN** an admin saves a place with a slug lacking both `-` and
  `_` (e.g. `zermatt`) or equal to a reserved name
- **THEN** model validation rejects the save with a friendly error,
  and any write path that bypasses validation (direct `.save()`, raw
  SQL) is rejected by the database check constraint — the routing
  invariant is a property of the data, enforced at storage level

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
sparse-fieldset selection: `categories`, `sources`, `amenity`
and `parties` (per the `geoplace-parties` capability — when this
change lands before that capability in any environment, the member
is absent from the response and not a valid `fields[places]` name,
becoming valid additively when that change lands). Without a
selection the response SHALL include every member that has data; with
a selection only the selected (plus required) members SHALL be
returned, with nested narrowing via `fields[parties]`,
`fields[categories]` and `fields[sources]` per the sparse-fieldsets
conventions. A detail block member SHALL be present only when the
place's `detail_type` matches the block and the detail row exists —
blocks of other types SHALL NOT be fabricated and requesting them
SHALL NOT error. Database work for unselected members SHALL be
skipped (field-selected gating, the search/nearby pattern). Future
detail models (admin, transport, natural) SHALL be exposed as sibling
optional members — one per detail model, added additively, following
this same rule; no wrapper object SHALL bundle the blocks.

#### Scenario: Default response includes everything present

- **WHEN** a client fetches an amenity place without a `fields`
  selection
- **THEN** the response carries every member that has data — base
  fields, `categories`, `sources`, `amenity` and `parties`
  (when associations exist)

#### Scenario: Narrowed selection

- **WHEN** a client sends `?fields[places]=slug,name,amenity`
- **THEN** the response carries only `slug`, `name` (plus the other
  required members) and `amenity`, and category/source/party
  queries are not executed

#### Scenario: Block of another type is absent, not an error

- **WHEN** a client fetches a `natural` place with
  `?fields[places]=slug,name,amenity`
- **THEN** the response is 200 with the requested members and no
  `amenity` member — the place's own type governs which blocks
  can exist

#### Scenario: Unknown block names 400 per the allowlist

- **WHEN** a client sends `?fields[places]=admin` before an
  admin block change has landed
- **THEN** the response is 400 `validation_error` naming the valid
  field names, per the sparse-fieldsets conventions

### Requirement: Path resolution and caching parity
The `{slug}` path parameter SHALL resolve against active, public
places only, and unknown, inactive or non-public slugs SHALL answer
404 with the single error contract body (`{"code": "not_found",
"detail": …}` plus the RFC 9457 members) with no distinction between
the cases. Unlike the removed `get_amenity` route, which filtered
only `is_active`, this endpoint additionally enforces `is_public` —
parity with `places/search`, `places/nearby` and the SEO surface
(bugfix-grade correction; the old route had zero consumers). A
successful fetch records a place visit per the visit-counter
behavior (best-effort, once existence is known). The detail route
SHALL be served with `Cache-Control:
public, max-age=60` and server-side response caching (`cache_page(60)`)
matching the `places/search` and `places/nearby` endpoints; language
and sparse-fieldset variants SHALL cache as distinct variants (the
cache keys on the full request URL). The endpoint is a singleton
resource, not a catalog/index document, so the time-based family
tier applies (`api-conventions`' evolving-document rule governs
catalog endpoints); a future ETag upgrade for the places family
would revisit this.

#### Scenario: Unknown slug answers the standard 404

- **WHEN** a client fetches a slug that does not exist
- **THEN** the response is 404 with `code="not_found"` and the RFC
  9457 members, `instance` identifying the requested path

#### Scenario: Non-public place is indistinguishable from missing

- **WHEN** a client fetches the slug of an inactive or non-public
  place
- **THEN** the response is the same 404 body as for an unknown slug —
  the endpoint is no existence oracle

#### Scenario: Cache headers match the family tier

- **WHEN** a client fetches a place detail
- **THEN** the response carries `Cache-Control: public, max-age=60`,
  and the same place fetched with `?lang=de` and `?lang=fr` caches as
  distinct variants
