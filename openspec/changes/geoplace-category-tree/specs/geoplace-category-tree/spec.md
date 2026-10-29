# Spec Delta: geoplace-category-tree

## ADDED Requirements

### Requirement: Namespace root and super-roots

The category tree SHALL provide a `map` namespace root (parent=None)
under which three super-roots exist: `amenity`, `admin`, `natural`.
Super-roots are `is_protected` (slug + parent readonly). Existing
vocabulary trees (`mode.*`, `role.*`, `relations.*`, `link_type.*`)
remain parentless — separate from the map tree.

#### Scenario: Tree structure after seeding
- **WHEN** the seed migration runs
- **THEN** `map → amenity → accommodation → hut` exists; identifiers
  are 2-level (`accommodation.hut`); `mode.*` and `role.*` remain
  parentless

### Requirement: CategoryKindContract model

The system SHALL provide a `CategoryKindContract` model (OneToOne on
the contract-group Category) with: `allowed_classifiers` (M2M to
Category — the classifier subtrees permitted under this group),
`has_operations` (Boolean — GeoPlaceOperation rows allowed), and
`has_seasonality` (Boolean — GeoPlaceSeasonality rows allowed).
Seeded from code (`PLACE_KINDS`), then admin-editable.

#### Scenario: Accommodation contract
- **WHEN** the seed runs
- **THEN** accommodation's contract has `allowed_classifiers=[mode]`,
  `has_operations=True`, `has_seasonality=True`

#### Scenario: Transport contract
- **WHEN** an admin enables `has_operations` for transport
- **THEN** transport places can receive GeoPlaceOperation rows
  without a deploy

#### Scenario: Admin contract
- **WHEN** the seed runs
- **THEN** administrative's contract has `allowed_classifiers=[]`,
  `has_operations=False`, `has_seasonality=False`

### Requirement: Operations and seasonality gated by contract

GeoPlaceOperation and GeoPlaceSeasonality writes SHALL be rejected
when the place's contract group does not enable them
(`has_operations=False` → no operation rows; `has_seasonality=False`
→ no seasonality rows).

#### Scenario: Seasonality rejected for admin place
- **WHEN** a seasonality write is attempted on a municipality
- **THEN** validation rejects it — the administrative contract has
  `has_seasonality=False`

### Requirement: kind_slug replaces detail_type

`GeoPlace.detail_type` SHALL be replaced by `GeoPlace.kind_slug`
(CharField, indexed) — the super-root slug derived on write from the
place's first category's ancestry (category → parent → parent).
Stored for tiles SQL; no enum check constraint (the tree validates).

#### Scenario: Hut place derives amenity
- **WHEN** a place is categorized as `accommodation.hut`
- **THEN** `kind_slug = "amenity"` (hut → accommodation → amenity)

#### Scenario: Municipality derives admin
- **WHEN** a place is categorized as `administrative.municipality`
- **THEN** `kind_slug = "admin"`

## MODIFIED Requirements

### Requirement: Kind contract registry → DB-driven

The kind contract SHALL be resolved from `CategoryKindContract`
(DB rows) instead of the `PLACE_KINDS` code registry. The code
registry becomes the seed source only. Classifier validation reads
the DB contract's `allowed_classifiers` M2M.

#### Scenario: Classifier validated against DB contract
- **WHEN** an association is written with classifier `mode.standard`
  on a `shopping.bakery` category
- **THEN** validation checks the shopping contract's
  `allowed_classifiers` (empty — mode not allowed) and rejects it
