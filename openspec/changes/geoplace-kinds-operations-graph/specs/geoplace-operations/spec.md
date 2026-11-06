# Spec Delta: geoplace-operations

## ADDED Requirements

### Requirement: GeoPlaceOperation typed operating facts

The system SHALL provide a `GeoPlaceOperation` model: one row per
`(geo_place, mode)` — the mode being a `mode.*` category — with a
nullable `capacity` (non-negative integer, DB-constrained; semantics
per kind: beds / seats / visitors), a structured `opening_hours` JSON
(weekly schema, per-mode), and an `extra` JSON overflow. Unique per
`(geo_place, mode)`; the mode category is RESTRICT.

**Invariant — capacity is per-mode, not per-category-per-mode:**
imports SHALL NOT emit two same-mode associations with differing
capacities; where multiple categories share a mode (the rare
same-category/open-closed coincidence), one operation row carries the
mode's single capacity.

#### Scenario: Hut capacities per mode
- **WHEN** a hut with 64 staffed beds and an 8-bed winter room is
  imported
- **THEN** two operation rows exist: `(hut, mode.standard, capacity=64)`
  and `(hut, mode.reduced, capacity=8)`

#### Scenario: Negative capacity rejected
- **WHEN** an operation row is written with `capacity=-1`
- **THEN** the database check constraint rejects it

#### Scenario: Per-mode opening hours
- **WHEN** a hut's standard mode operates 07:00–21:00 and its reduced
  mode is always accessible
- **THEN** each mode's operation row carries its own `opening_hours`

### Requirement: Capacity moves from association extra

The wodore import and the schema write path SHALL write `capacity` to
operation rows; the association `extra` no longer carries it for new
writes, the `capacity` key is removed from the seeded accommodation
`CategoryExtraSchema` (no silent second home), and existing
association-extra capacity data relocates via the drop-and-re-import.
Association `extra` remains the schema-validated flexible layer for
unknown attributes.

#### Scenario: Import writes operation rows
- **WHEN** `import_geoplaces -s wodore` imports a hut
- **THEN** association rows carry only classification (category ×
  mode) and the capacities live on the operation rows

### Requirement: Capacity stays tile-visible

The tiles view SHALL keep exposing per-place capacities after the
move — the categories JSON entry of each mode association (or a
feature-level property) carries the mode's `operation.capacity`, so
tile consumers PR #446 made capacity-visible to keep working.

#### Scenario: Tile payload keeps capacity
- **WHEN** tiles are requested for a hut-derived place
- **THEN** each mode entry in the tile payload includes its
  operation capacity
