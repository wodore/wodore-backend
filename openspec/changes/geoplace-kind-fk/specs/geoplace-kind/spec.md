# Spec Delta: geoplace-kind-fk

## ADDED Requirements

### Requirement: GeoPlace.kind foreign key

`GeoPlace` SHALL carry a nullable `kind` foreign key to `Category`
(indexed, `on_delete=SET_NULL`), derived on write from the first
category association by `(order, slug)` — stored alongside `domain`
in one derivation step. Places without associations have `kind=NULL`
and `domain="none"`.

#### Scenario: Hut place stores its anchor
- **WHEN** a place is written with associations
  `[accommodation.hut (+mode.standard), accommodation.unknown
  (+mode.reduced)]`
- **THEN** `place.kind.identifier == "accommodation.hut"` and
  `place.domain == "amenity"`

#### Scenario: Backfill
- **WHEN** migration 0073 runs on existing data
- **THEN** every place's `kind` equals its first association by
  `(order, slug)`; association-less places stay NULL

#### Scenario: FK stays in sync
- **WHEN** any write path (schema upsert, wodore import, OSM bulk)
  writes a place's associations
- **THEN** `kind` is re-derived in the same transaction — the FK
  always equals the first association after save

### Requirement: kind API member with classifier and extra

The `kind` member on search/nearby/detail responses SHALL be
`{identifier, slug, color, name, symbol, classifier, extra}` — the
anchor category ref plus the anchor association's classifier
(`mode.*` etc.) and schema-validated extra attributes.

#### Scenario: Season classification visible via kind alone
- **WHEN** a hut's anchor association carries
  `classifier=mode.standard`
- **THEN** `kind.classifier == "mode.standard"` in the response —
  no other member needed for classification display

### Requirement: categories as sub-categories

The `categories` member SHALL list only non-anchor associations
(sub-categories) — the anchor kind row no longer appears in it.

#### Scenario: No duplication
- **WHEN** a place has the anchor + two additional categories
- **THEN** `kind` carries the anchor; `categories` lists exactly the
  two additional associations

## MODIFIED Requirements

### Requirement: kind filter matches the FK

The `kind` filter parameter on search/nearby SHALL match places
whose `kind` FK (identifier or slug) is in the provided list — a
direct indexed FK join instead of the association lateral.

#### Scenario: Filter by identifier
- **WHEN** `?kind=accommodation.hut`
- **THEN** only places with `kind.identifier ==
  "accommodation.hut"` match
