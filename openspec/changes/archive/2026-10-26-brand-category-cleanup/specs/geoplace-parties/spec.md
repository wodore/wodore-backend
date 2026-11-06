# Spec Delta: brand-category-cleanup

## MODIFIED Requirements

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
