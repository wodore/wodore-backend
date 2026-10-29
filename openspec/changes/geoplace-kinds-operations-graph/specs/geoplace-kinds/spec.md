# Spec Delta: geoplace-kinds

## ADDED Requirements

### Requirement: Kind contract registry

The system SHALL map each root category parent to a place-kind
contract in code: the `detail_type` value and the classifier subtrees
allowed on associations under that parent. The place's kind is its
anchoring category (the parent of the first category by
`(order, slug)`); no marker association exists.

**Registry values are constrained**: every mapped `detail_type` MUST
be one of the `GeoPlace.detail_type` check-constraint values
(`amenity`, `transport`, `admin`, `natural`, `none`) — a test asserts
`registry values ⊆ constraint set`.

**Vocabulary roots are not kinds**: `external_link`, `link_type`,
`mode`, `role`, `relations` (and any future classifier/uri
vocabularies) are excluded from kind resolution; a place anchored to
one resolves to the default kind.

**Pinned mapping** (live root tree; gaps are the default):

| root parent | detail_type | classifiers |
|---|---|---|
| `accommodation` | amenity | `mode` |
| `tourism`, `sport`, `shopping`, `food_supply`, `restaurant`, `groceries`, `services`, `finance`, `health_and_emergency`, `outdoor_services`, `utilities`, `automotive`, `meteo`, `availability` | amenity | — |
| `transport` | transport | — |
| `administrative`, `populated_place` | admin | — |
| `terrain`, `hydrographic` | natural | — |
| *(default / vocabulary roots)* | amenity | — |

#### Scenario: Mode restricted to accommodation
- **WHEN** an association is written with classifier `mode.standard`
  on a `groceries.shop` category
- **THEN** validation rejects it — `mode` is allowed only under the
  accommodation kind

#### Scenario: Kind of a multi-kind place is deterministic
- **WHEN** a place carries categories from two different parents
- **THEN** its kind is the parent of the first category by
  `(order, slug)` — deterministic across reads

#### Scenario: Vocabulary root never anchors a kind
- **WHEN** a place's first category resolves to a vocabulary root
  (e.g. `mode.*`)
- **THEN** the default kind applies — no kind contract is looked up
  on vocabulary parents

### Requirement: detail_type derived on write

`GeoPlace.detail_type` SHALL remain a stored column (consumed by tile
and clustering SQL) but SHALL be populated from the kind contract on
every write path (create/update schema path, admin save) instead of
being declared by input schemas.

#### Scenario: OSM import no longer declares detail_type
- **WHEN** a `groceries.shop` place is imported
- **THEN** `detail_type` is stored as `amenity`, derived from the
  kind registry — the input schema carries no detail_type

### Requirement: Protected vocabulary categories

`Category` SHALL carry an `is_protected` boolean (default false).
Seeded vocabulary (mode.*, role.*, relations.*, root kind parents,
uri-kind roots) SHALL be protected: deletion is blocked in admin and
by model validation, while names, colors and symbols remain editable.
Code couples to slugs only.

#### Scenario: Protected category cannot be deleted
- **WHEN** an admin attempts to delete `mode.reduced`
- **THEN** the deletion is refused with a clear message

#### Scenario: Presentation stays editable
- **WHEN** an admin renames or recolors a protected category
- **THEN** the edit is saved — only deletion is blocked
