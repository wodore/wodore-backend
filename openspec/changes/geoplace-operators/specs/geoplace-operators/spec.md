# Spec Delta: geoplace-operators

## ADDED Requirements

### Requirement: Operator entity with localized name and links

The system SHALL provide an `Operator` entity with a unique slug, a
localized name, an optional localized note, active/public flags, and any
number of ordered `ExternalLink` associations (shared link entities with
i18n labels, link types, and health checks).

#### Scenario: Operator with multiple links
- **WHEN** an operator "SAC Bern" is created with a website link and a
  booking link
- **THEN** both links are associated with the operator in the given
  order and each carries its own i18n label

#### Scenario: Slug uniqueness
- **WHEN** an operator is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

### Requirement: Role-based GeoPlace association

The system SHALL associate operators with geoplaces through
`GeoPlaceOperatorAssociation` with a role of `operator` or `brand`,
unique per `(geo_place, operator, role)`. The same operator MAY hold
both roles for the same place.

#### Scenario: Hut operated by a club
- **WHEN** a hut-derived geoplace is linked to operator "sac-bern" with
  role `operator`
- **THEN** the association exists exactly once and API/admin consumers
  see role `operator`

#### Scenario: Duplicate association rejected
- **WHEN** an association is saved with the same place, operator, and
  role as an existing one
- **THEN** the save is rejected by the uniqueness constraint

#### Scenario: Invalid role rejected
- **WHEN** an association is saved with a role outside
  `{operator, brand}`
- **THEN** the save is rejected by the check constraint

### Requirement: Brand category replacement

The system SHALL replace `AmenityDetail.brand` (Category FK) with
operator associations of role `brand`. A data migration SHALL convert
every existing brand Category reference into an Operator (slug and
localized name preserved) plus its association. The `root.brand`
category subtree SHALL remain in the database (rollback safety) until a
later cleanup.

#### Scenario: Existing brand migrates
- **WHEN** migrations run on a database where an amenity detail
  references brand category `brand.volg`
- **THEN** an Operator `volg` (localized name from the category) exists
  and the place carries an association with role `brand`, and the
  amenity detail no longer has a brand FK

#### Scenario: OSM brand tag
- **WHEN** the OSM import encounters a place with `brand=Volg`
  (single value)
- **THEN** an Operator `volg` is get_or_create'd (no category is
  created) and associated with role `brand`

#### Scenario: OSM operator tag
- **WHEN** the OSM import encounters a place with a single-value
  `operator` tag
- **THEN** an Operator is get_or_create'd from the slugified value and
  associated with role `operator` (multi-value `;` lists are skipped)

### Requirement: Owner merge into operators

The system SHALL provide an idempotent management command that merges
`owners.Owner` rows into Operators (slug, localized name, note
preserved; url converted to an ExternalLink). The command SHALL support
dry-run. The `Owner` model SHALL remain unchanged for `Hut.hut_owner`
until the huts app is removed.

#### Scenario: Merge run
- **WHEN** `import_operators` runs against an owners table containing
  "SAC Bern" with url and note
- **THEN** an Operator `sac-bern` exists with the localized name, note,
  and one website link; re-running changes nothing

#### Scenario: Wodore hut import links the operator
- **WHEN** the wodore hut import processes a hut with `hut_owner` and
  the merge has run
- **THEN** the resulting GeoPlace carries an operator association with
  role `operator` referencing the merged operator

### Requirement: API exposes place operators

GeoPlace responses SHALL include an `operators` list
(`[{role, slug, name, links}]`) under the `fields[places]`
sparse-fieldset selection, with nested narrowing via
`fields[operators]` per the sparse-fieldsets conventions. The additive
change SHALL be registered in the API changelog per `api-conventions`.

#### Scenario: Detail carries operators
- **WHEN** a client requests a place whose operator association has
  role `operator` and two links, with operators selected
- **THEN** the response contains `operators: [{role: "operator", slug,
  name, links: [...]}]`

### Requirement: Admin management of operators

The admin SHALL provide an Operator model admin (localized name, links
with ordering) and a GeoPlace inline for operator associations (role +
operator autocomplete). Manual inline edits SHALL mark the place
`is_modified` and record the association in `protected_fields`
(explicit wiring — associations carry no automatic tracking). The
amenity admin SHALL no longer offer the brand field.

#### Scenario: Editor links an operator
- **WHEN** an editor adds operator "migros" with role `brand` to a
  place in the admin and saves
- **THEN** the association exists and the place is marked modified with
  the operator association recorded as protected
