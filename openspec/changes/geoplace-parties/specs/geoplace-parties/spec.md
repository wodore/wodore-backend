# Spec Delta: geoplace-parties

## ADDED Requirements

### Requirement: Party entity with localized name and links

The system SHALL provide a `Party` entity with a unique slug, a
localized name, an optional localized note, active/public flags, a
review status, and any number of ordered `ExternalLink` associations
(shared link entities with i18n labels, link types, and health checks).

#### Scenario: Party with multiple links
- **WHEN** a party "SAC Bern" is created with a website link and a
  booking link
- **THEN** both links are associated with the party in the given order
  and each carries its own i18n label

#### Scenario: Slug uniqueness
- **WHEN** a party is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

### Requirement: Role category vocabulary

The system SHALL provide a `role` parent category with children
`operator`, `brand`, and `owner`, created by data migration and
manageable in the category admin. Additional role children MAY be added
later via migration and spec delta.

#### Scenario: Vocabulary exists after migrate
- **WHEN** migrations run on a fresh database
- **THEN** the `role.*` categories exist and are active

### Requirement: Role-classified GeoPlace association

The system SHALL associate parties with geoplaces through
`GeoPlaceParty` whose role references exactly one category whose parent
is `role`, unique per `(geo_place, party, role)`. Multiple roles for
the same place–party pair SHALL be expressed as multiple association
rows. Role and party references SHALL NOT be deletable while in use
(RESTRICT).

#### Scenario: Hut owned by a club
- **WHEN** a hut-derived geoplace is linked to party "sac-bern" with
  role `role.owner`
- **THEN** the association exists exactly once and API/admin consumers
  see role `role.owner`

#### Scenario: Same party, two roles
- **WHEN** a place is linked to "migros" with role `role.brand` and
  again with role `role.operator`
- **THEN** both associations exist as separate rows

#### Scenario: Role outside the role subtree rejected
- **WHEN** a `GeoPlaceParty` is saved with a role whose parent slug is
  not `role`
- **THEN** the save is rejected with a validation error (in `clean()`
  and in the schema import path)

#### Scenario: Duplicate association rejected
- **WHEN** an association is saved with the same place, party, and role
  as an existing one
- **THEN** the save is rejected by the uniqueness constraint

### Requirement: Brand category replacement

The system SHALL replace `AmenityDetail.brand` (Category FK) with party
associations of role `role.brand`. A data migration SHALL convert every
existing brand Category reference into a Party (slug and localized name
preserved) plus its association. The `root.brand` category subtree
SHALL remain in the database (rollback safety) until a later cleanup.

#### Scenario: Existing brand migrates
- **WHEN** migrations run on a database where an amenity detail
  references brand category `brand.volg`
- **THEN** a Party `volg` (localized name from the category) exists and
  the place carries an association with role `role.brand`, and the
  amenity detail no longer has a brand FK

#### Scenario: OSM brand tag
- **WHEN** the OSM import encounters a place with `brand=Volg`
  (single value)
- **THEN** a Party `volg` is get_or_create'd (no category is created)
  and associated with role `role.brand`

#### Scenario: OSM operator tag
- **WHEN** the OSM import encounters a place with a single-value
  `operator` tag
- **THEN** a Party is get_or_create'd from the slugified value (review
  status `review`) and associated with role `role.operator`
  (multi-value `;` lists are skipped)

### Requirement: Owner merge into parties

The system SHALL provide an idempotent management command that merges
`owners.Owner` rows into Parties (slug, localized name, note preserved;
url converted to an ExternalLink). The command SHALL support dry-run.
The `Owner` model SHALL remain unchanged for `Hut.hut_owner` until the
huts app is removed.

#### Scenario: Merge run
- **WHEN** `import_parties` runs against an owners table containing
  "SAC Bern" with url and note
- **THEN** a Party `sac-bern` exists with the localized name, note, and
  one website link; re-running changes nothing

#### Scenario: Wodore hut import links the party
- **WHEN** the wodore hut import processes a hut with `hut_owner` and
  the merge has run
- **THEN** the resulting GeoPlace carries a party association with role
  `role.owner` referencing the merged party

### Requirement: API exposes place parties

GeoPlace responses SHALL include a `parties` list
(`[{role, slug, name, links}]`, `role` as category identifier) under
the `fields[places]` sparse-fieldset selection, with nested narrowing
via `fields[parties]` per the sparse-fieldsets conventions. The
additive change SHALL be registered in the API changelog per
`api-conventions`.

#### Scenario: Detail carries parties
- **WHEN** a client requests a place whose party association has role
  `role.operator` and two links, with parties selected
- **THEN** the response contains
  `parties: [{role: "role.operator", slug, name, links: [...]}]`

### Requirement: Admin management of parties

The admin SHALL provide a Party model admin (localized name, links with
ordering) and a GeoPlace inline for party associations (party
autocomplete, role autocomplete scoped to the `role` subtree). Manual
inline edits SHALL mark the place `is_modified` and record the
association in `protected_fields` (explicit wiring — associations carry
no automatic tracking). The amenity admin SHALL no longer offer the
brand field.

#### Scenario: Editor links a party
- **WHEN** an editor adds party "migros" with role `role.brand` to a
  place in the admin and saves
- **THEN** the association exists and the place is marked modified with
  the party association recorded as protected
