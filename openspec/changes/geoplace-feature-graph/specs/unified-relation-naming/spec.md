## ADDED Requirements

### Requirement: Unified relation field naming
The system SHALL rename `GeoPlaceCategory.classifier` to `relation` and `ExternalLink.link_type` to `relation` across models, migrations, schemas, API fields and admin, making `relation` the consistent field name for all category-typed association fields.

#### Scenario: Renamed fields are live
- **WHEN** code or API payloads reference the association type of a GeoPlaceCategory or ExternalLink
- **THEN** the field is named `relation` and no `classifier` / `link_type` references remain (`grep -r "\.classifier"`, `grep -r "\.link_type"` return nothing under server/apps)

#### Scenario: Existing data preserved
- **WHEN** the rename migrations run
- **THEN** all existing classifier/link_type values remain intact on the renamed columns

### Requirement: Relation and service category trees
The system SHALL provide Category fixture trees: `relations/` (part_of, near, serves, access_point), `service/` (standard, reduced), `link_types/` (website, booking, social, phone) and `brand/`, loadable idempotently via a `relation_categories` fixture.

#### Scenario: Fixtures load idempotently
- **WHEN** `app loaddata relation_categories` runs twice
- **THEN** each relation/service/link/brand category exists exactly once with correct parentage

### Requirement: Phone contacts via ExternalLink
Phone contacts SHALL be represented as `ExternalLink` entries with `tel:` URIs (relation category `link_types/phone`) instead of dedicated phone fields, with a label for the contact name.

#### Scenario: Phone stored as tel URI
- **WHEN** a place's reception phone +41 27 967 22 15 is recorded
- **THEN** an ExternalLink exists with `url = "tel:+41279672215"`, relation `phone`, and a human label
