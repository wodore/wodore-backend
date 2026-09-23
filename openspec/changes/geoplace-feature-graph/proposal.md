## Why

GeoPlace hierarchies and contextual relationships are currently expressed through
a `parent` self-FK (hierarchy only) and expensive spatial operations at query
time. Amenity details (opening months, capacity, hours) live in a dedicated
`AmenityDetail` model that only serves accommodations, while the equivalent
association fields are inconsistently named (`classifier`, `link_type`). A
semantic **feature graph** based on the existing `Category` model plus a generic
**operating-mode** model gives fast hierarchical/contextual queries without
spatial operations, one consistent `relation` vocabulary, and coverage for all
place types (huts, restaurants, shops, museums, medical) — replacing
`AmenityDetail` entirely.

Source documents: `_work/260313_geoplace_feature_graph_spec.md` and
`_work/260313_feature_graph_implementation.md` (converted into this change).

## What Changes

- **New `GeoPlaceRelation` model**: one-direction semantic edges between
  GeoPlaces, typed by a `Category` under `relations/` (part_of, near, serves,
  access_point); unique `(from_place, to_place, relation)`, no self-loops,
  confidence + extra JSON for auto-generated edges. **BREAKING**: the
  `GeoPlace.parent` field is removed — hierarchy is expressed exclusively
  through `part_of` relations (data migration provided).
- **New `GeoPlaceOperation` model** (replaces `AmenityDetail`, which is
  **deleted**): generic operating modes per place — nullable capacity (beds /
  seats / visitors by type), twelve `month_XX` integer columns (0–100 opening
  percentage, DB-validated), free-text `hours` string, `extra` JSONB — with a
  1-based `Month` IntEnum and dict-like `MonthAccessor`.
- **Unified `relation` naming**: `GeoPlaceCategory.classifier` → `relation`,
  `ExternalLink.link_type` → `relation` (**BREAKING** renames, including API
  field names).
- **Category trees** loaded as fixtures: `relations/` (part_of, near, serves,
  access_point), `service/` (standard, reduced), `link_types/` (website,
  booking, social, phone), `brand/`.
- **Phones via `ExternalLink`** with `tel:` URIs instead of phone fields.
- **GeoPlace helpers**: `add_relation`, `get_related_places` (direction-aware).
- **Auto-generation hooks** for relations during import (spatial containment →
  `part_of`, proximity → `serves`, OSM operator tags → brand).

## Capabilities

### New Capabilities
- `geoplace-feature-graph`: the `GeoPlaceRelation` model, constraints, reverse
  querying, GeoPlace helper methods, removal of `GeoPlace.parent` with data
  migration, and relation auto-generation.
- `geoplace-operation-modes`: the `GeoPlaceOperation` model (capacity, month
  percentage columns, hours, extra), `Month` enum + `MonthAccessor` semantics,
  and the `AmenityDetail` → `GeoPlaceOperation` data migration.
- `unified-relation-naming`: the `classifier` → `relation` and `link_type` →
  `relation` renames (model + API + admin), the Category fixture trees, and
  phone contacts via `tel:` ExternalLinks.

### Modified Capabilities

(none — existing specs untouched; `dj-runner` unaffected)

## Impact

- **Models** (5 critical files): `geometries/_associations.py`,
  `geometries/_geoplace.py` (remove parent), new `geometries/_operation.py`,
  `external_links/models.py`, `geometries/models/__init__.py`.
- **Schemas/API**: `geometries/schemas/_output.py`, `_input.py` (AmenityDetail
  schema → Operation schema), `geometries/api.py` amenity filtering/serialization.
- **Imports**: `geoplaces_import_osm.py` (heavy: opening_hours/brand extraction,
  AmenityDetailInput → GeoPlaceOperationInput), `test_import_performance.py`.
- **Admin**: `external_links/admin.py` (link_type → relation), `geometries/admin/_geoplace.py`.
- **Migrations**: ~6, in strict order (renames → new models → fixtures → data
  migrations → field/model removals).
- **~17 files affected** overall; API consumers see renamed fields (BREAKING).
