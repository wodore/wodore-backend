# Spec Delta: geoplace-detail-retirement

## ADDED Requirements

### Requirement: Place-level extra validation

`GeoPlace.extra` SHALL be validated against the place's kind schema:
`resolve_extra_schema` gains a place-level resolution (kind root
parent first, explicit place-level schema row override) and the
validation runs on the same write paths as association extra (model
save/clean, the schema upsert, admin save) with the same fail-open
and metaschema guardrails. The admin renders `GeoPlace.extra` through
the JSON-Schema widget with the resolved kind schema.

#### Scenario: Municipality facts validated
- **WHEN** a municipality place stores `population` in extra
- **THEN** the administrative kind schema validates it as a
  non-negative integer — invalid values are rejected on save

### Requirement: AmenityDetail removed

`AmenityDetail` SHALL be deleted. Opening hours move to
`GeoPlaceOperation.opening_hours`; `operating_status` is not migrated
(a uniform constant in the data — the OSM importer writes `open` on
every row) and reads default to `open` to preserve the wire shape;
`opening_months` maps to `GeoPlaceSeasonality` (fuzzy mapping). The
API amenity block keeps its wire shape, served from operation rows
and place extra.

#### Scenario: API amenity block unchanged on the wire
- **WHEN** a client requests `fields[places]=amenity`
- **THEN** the response block has the same fields as before
  (`operating_status` reads as `open` by default), sourced from the
  new homes

### Requirement: AdminDetail removed

`AdminDetail` SHALL be deleted; `population`, `postal_code` and
`iso_code` move to `GeoPlace.extra` validated by the
`administrative` kind schema (seeded from code, admin-editable).

#### Scenario: Municipality scalars live in place extra
- **WHEN** a municipality place is imported or edited
- **THEN** its population, postal code and ISO code are stored and
  validated in `GeoPlace.extra` — no AdminDetail row exists

### Requirement: Booking attribution without stored booleans

Booking SHALL be expressed through existing primitives: a
`uri.booking` ExternalLink on the place, the
`GeoPlaceSourceAssociation` (organization + source_id — the same join
availability uses), and optionally a party with `role.source`.
`is_bookable` SHALL be derived from the presence of these, never
stored.

#### Scenario: Bookable hut
- **WHEN** a hut place has a `uri.booking` link and a source
  association
- **THEN** it is bookable by derivation — no stored flag exists
