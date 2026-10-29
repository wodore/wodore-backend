# Proposal: geoplace-category-tree

## Why

The category tree is flat at the root level (~20 root parents with no
grouping), `GeoPlace.detail_type` is a redundant 5-value enum derivable
from the tree, and the kind contract (`PLACE_KINDS`) lives only in
code — admins can't evolve which models apply to which category
groups without a deploy. This change restructures the tree with
super-roots, moves the kind contract into the DB (admin-editable,
`CategoryExtraSchema` parity), and retires `detail_type`.

## What Changes

- **Tree restructure** (drop + reimport — staging only):
  ```
  map (namespace root, parent=None)
  ├── amenity (super-root)
  │   ├── accommodation (contract group)  ← identifier root
  │   │   └── hut (kind)                  ← identifier child
  │   ├── shopping (contract group)
  │   │   └── bakery
  │   ├── tourism / sport / groceries / ...
  │   └── transport
  │       └── bus_stop
  ├── admin (super-root)
  │   └── administrative
  │       └── municipality
  └── natural (super-root)
      ├── terrain
      │   └── peak
      └── hydrographic
          └── lake
  ```
  Identifiers stay 2-level (`accommodation.hut`): the identifier root
  is the contract group (level 2), not the super-root. `map` is the
  namespace root separating map categories from vocabulary trees
  (`mode.*`, `role.*`, `relations.*`, `link_type.*` — these stay
  parentless).

- **`CategoryKindContract` model** (DB, admin-editable):
  - `category = OneToOneField(Category)` — the contract group
    (accommodation, shopping, transport…)
  - `allowed_classifiers = ManyToManyField(Category)` — classifier
    categories permitted under this group (e.g., mode.standard,
    mode.reduced for accommodation)
  - `has_operations = BooleanField()` — places under this group can
    have GeoPlaceOperation rows
  - `has_seasonality = BooleanField()` — places under this group can
    have GeoPlaceSeasonality rows
  - Seeded from `PLACE_KINDS` (code), then admin-editable

- **`GeoPlace.detail_type` retired**: replaced by the super-root slug
  (derived from the place's first category's ancestry, stored as
  `kind_slug` CharField for tiles SQL — same derive-but-store pattern).
  The check constraint changes from the 5-value enum to free-form
  (validated by the tree).

- **Kind contract drives validation**: the `validate_attributes`
  kind guard reads the DB contract instead of the code registry;
  operations and seasonality writes check `has_operations`/
  `has_seasonality` on the place's contract group.

- **Protected vocabulary extended**: super-roots and the map root are
  `is_protected` — slug, parent readonly; contract groups editable
  (admin can re-parent a group under a different super-root if
  taxonomies evolve).

## Capabilities

### New Capabilities

- `geoplace-category-tree`: the 3-level tree structure (map →
  super-root → contract group → kind), identifier semantics,
  CategoryKindContract model, super-root slug derivation

### Modified Capabilities

- `geoplace-kinds` (from `geoplace-kinds-operations-graph`): the kind
  contract moves from code registry to DB model; validation reads
  from DB; operations/seasonality gated by contract booleans

## Impact

- **Models**: `CategoryKindContract` (new, geometries app);
  `GeoPlace.detail_type` → `GeoPlace.kind_slug` (rename + semantic
  change); existing associations/operations/seasonality/relation
  models unchanged
- **Migrations**: data migration creating super-roots + re-parenting
  (or drop + reimport — staging only); `CategoryKindContract` schema
  migration + seed from `PLACE_KINDS`
- **Code**: `kinds.py` registry becomes the seed source (not the
  runtime authority); `validate_attributes` reads DB; write paths
  check contract booleans; tiles SQL reads `kind_slug` instead of
  `detail_type`; OSM import unchanged (categories re-seeded with the
  new tree); admin gets `CategoryKindContractAdmin`
- **Breaking**: `detail_type` column renamed → tiles view and any
  consumer reading `gp.detail_type` must update; category tree shape
  changes mean `parent__isnull=True` no longer finds contract groups

## Out of scope

- Hut → GeoPlace data migration (next change after this)
- Availability Phase D/E
- Transport schedules
- OSM category re-import (the tree change is a drop + reimport)
