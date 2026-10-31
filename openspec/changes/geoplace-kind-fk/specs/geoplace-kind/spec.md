# Spec Delta: geoplace-kind-fk

## ADDED Requirements

### Requirement: GeoPlace.kind foreign key

`GeoPlace` SHALL carry a nullable `kind` foreign key to `Category`
(indexed, `on_delete=SET_NULL`), derived on write from the first
category association by anchor order — `(classifier priority, order,
slug)`: associations classified `mode.standard` outrank every other
association regardless of order, ties fall through to
`(order, slug)` — stored alongside `domain` in one derivation step.
Places without associations have `kind=NULL` and `domain="none"`.

Rationale (PO decision on the anchoring fix): the D4 reduced-mode
fallback `accommodation.unknown` carries `order=0` — without the
priority tier it would always anchor over a hut's real open type
(camping 25 … alp 55), and 1285 staging places served no `kind`
member at all (the legacy pk-0 anchor is falsy; fixed alongside).

#### Scenario: Hut place stores its anchor
- **WHEN** a place is written with associations
  `[accommodation.hut (+mode.standard), accommodation.unknown
  (+mode.reduced)]`
- **THEN** `place.kind.identifier == "accommodation.hut"` and
  `place.domain == "amenity"` — the standard association anchors
  even though `accommodation.unknown` has the lower order

#### Scenario: Reduced-only place anchors deterministically
- **WHEN** a place has only reduced facts (no `mode.standard`
  association, e.g. the D4 fallback alone)
- **THEN** the historical `(order, slug)` rule applies — the
  fallback `accommodation.unknown` anchors

#### Scenario: Classifier-less associations unchanged
- **WHEN** a place's associations carry no classifier (geonames,
  OSM)
- **THEN** the anchor is the first category by `(order, slug)` as
  before — the priority tier changes nothing

#### Scenario: Backfill
- **WHEN** migration 0073 runs on existing data
- **THEN** every place's `kind` equals its first association by
  `(order, slug)`; association-less places stay NULL

#### Scenario: Re-anchor migration
- **WHEN** migration 0074 (`0074_reanchor_kind_mode_standard`) runs
  on data written before the classifier-aware rule
- **THEN** every place with a `mode.standard` association is
  re-anchored by the new rule (places without one are untouched);
  reverse restores the order-only rule on the same subset

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

#### Scenario: Legacy pk-0 anchors serve the kind member
- **WHEN** a place's anchor category carries pk 0 (legacy HutType
  ids preserved into Category pks, e.g. `accommodation.unknown`)
- **THEN** the `kind` member is served — pk 0 is a valid anchor,
  never falsy-skipped

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
