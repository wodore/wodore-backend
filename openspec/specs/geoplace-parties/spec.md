# geoplace-parties Specification

## Purpose
Model the entities behind places — brands, operators, owners, sources —
as a neutral first-class `Party` entity (ISO 19115-1 `CI_Party`),
associated to geoplaces through role-classified associations
(`GeoPlaceParty` + `role.*` category vocabulary), replacing the former
brand-category FK and absorbing the hut `Owner` model.

## Requirements
### Requirement: Party entity with localized name and links

The system SHALL provide a `Party` entity with a unique short minted
slug (public identifier, `{base}-{random}` per the short-slug-minting
capability), an `extra` JSONB payload (GIN-indexed) carrying the
`osm_name` import identity (normalized name; owner slugs ride the same
key), a localized name, an optional localized note, active/public
flags, a review status, any number of ordered `ExternalLink`
associations (shared link entities with i18n labels, link types, and
health checks), and an optional symbol (two nullable Symbol FKs —
color and mono; the map-styling primitive variant is not used for
parties).

#### Scenario: Party with multiple links
- **WHEN** a party "SAC Bern" is created with a website link and a
  booking link
- **THEN** both links are associated with the party in the given order
  and each carries its own i18n label

#### Scenario: Optional symbol resolves
- **WHEN** a party has symbol FKs set and its symbol URLs are resolved
- **THEN** the color and mono URLs are returned (same helper pattern
  as category symbols); a party without symbols resolves to no
  symbol data

#### Scenario: Slug uniqueness
- **WHEN** a party is saved with a slug that already exists
- **THEN** the save is rejected with a validation error

#### Scenario: Identity rides extra
- **WHEN** an import resolves a party by name and no row carries the
  matching `extra.osm_name` identity yet
- **THEN** an exactly-named existing party is adopted (identity
  stamped) or the party is created with the identity — never a
  same-named duplicate

### Requirement: Role category vocabulary

The system SHALL provide a `role` parent category with children
`operator`, `brand`, and `source`, created by data migration
and manageable in the category admin. Additional role children MAY be
added later via migration and spec delta.

#### Scenario: Vocabulary exists after migrate
- **WHEN** migrations run on a fresh database
- **THEN** the `role.*` categories exist and are active

### Requirement: Role-classified GeoPlace association

The system SHALL associate parties with geoplaces through
`GeoPlaceParty` whose role references exactly one category whose parent
is `role`, unique per `(geo_place, party, role)`. The association SHALL
be place-level: available for every geoplace regardless of
`detail_type` (amenity, transport, admin, natural, none). Multiple
roles for the same place–party pair SHALL be expressed as multiple
association rows. Role and party references SHALL NOT be deletable
while in use (RESTRICT).

#### Scenario: Hut run by a club
- **WHEN** a hut-derived geoplace is linked to party "sac-bern" with
  role `role.operator`
- **THEN** the association exists exactly once and API/admin consumers
  see role `role.operator`

#### Scenario: Party on a non-amenity place
- **WHEN** a transport geoplace (e.g. a cable car) is linked to its
  operating company with role `role.operator`
- **THEN** the association works identically to amenity places —
  parties are not gated on `detail_type`

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
preserved) plus its association. A cleanup migration SHALL then remove
the legacy `root.brand` category subtree — its `GeoPlaceCategory`
associations first (superseded by the party associations), then the
parent (children cascade) — idempotently and without a data-restoring
reverse.

#### Scenario: Existing brand migrates
- **WHEN** migrations run on a database where an amenity detail
  references brand category `brand.volg`
- **THEN** a Party `volg` (localized name from the category) exists and
  the place carries an association with role `role.brand`, and the
  amenity detail no longer has a brand FK

#### Scenario: Brand subtree cleaned up
- **WHEN** the cleanup migration runs on a database still carrying the
  `root.brand` subtree (with places associated to its children)
- **THEN** the associations to `brand.*` children and the subtree rows
  are gone, non-brand vocabularies (including `role.*`) are untouched,
  and the party associations from the conversion remain

#### Scenario: Cleanup is idempotent
- **WHEN** the cleanup migration runs on a database without the
  `root.brand` subtree (fresh test database, re-run)
- **THEN** the migration is a no-op

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
A data migration SHALL perform the same merge once at migrate time, so
environments provisioning via `migrate` alone receive the parties and
links (idempotent; the command remains the re-sync for Owner rows
arriving later). The `Owner` model SHALL remain unchanged for
`Hut.hut_owner` until the huts app is removed.

#### Scenario: Merge run
- **WHEN** `import_parties` runs against an owners table containing
  "SAC Bern" with url and note
- **THEN** a Party `sac-bern` exists with the localized name, note, and
  one website link; re-running changes nothing

#### Scenario: Wodore hut import links the party
- **WHEN** the wodore hut import processes a hut with `hut_owner` and
  the merge has run
- **THEN** the resulting GeoPlace carries a party association with role
  `role.operator` referencing the merged party

### Requirement: API exposes place parties

GeoPlace responses SHALL include a `parties` list
(`[{role, slug, name, links, symbol}]`, `role` as category identifier)
under the `fields[places]` sparse-fieldset selection, with nested
narrowing via `fields[parties]` per the sparse-fieldsets conventions.
The changelog picks the additive change up automatically at release
(built from PR titles — no manual entry).

#### Scenario: Detail carries parties
- **WHEN** a client requests a place whose party association has role
  `role.operator` and two links, with parties selected
- **THEN** the response contains
  `parties: [{role: "role.operator", slug, name, links: [...], symbol}]`
  with `symbol` present when the party has symbols set

### Requirement: Admin management of parties

The admin SHALL provide a Party model admin (localized name, links
with ordering) and a GeoPlace inline for party associations (party
autocomplete, role autocomplete scoped to the `role` subtree). Manual
inline edits SHALL mark the place `is_modified` and record
role-scoped protection in `protected_fields` (`{"parties": [...]}`,
the union of changed, added and deleted roles; a legacy flat
`"parties"` entry shields all roles and is kept). Manual external-link
and category inline edits SHALL mark flat `"links"` / `"categories"`
protection. The amenity admin SHALL no longer offer the brand field.

#### Scenario: Editor links a party
- **WHEN** an editor adds party "migros" with role `role.brand` to a
  place in the admin and saves
- **THEN** the association exists, the place is marked modified, and
  only `role.brand` is recorded as protected — an import may still
  add other roles to that place
