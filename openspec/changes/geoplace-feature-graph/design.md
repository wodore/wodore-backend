## Context

Today, GeoPlace hierarchy is a `parent` self-FK; contextual relationships
(bus stop serves village, hut near glacier) have no representation and would
require spatial operations (`ST_Within`, distance) at query time. Operating
details (open months as fuzzy strings, capacity, hours) live in
`AmenityDetail`, which is accommodation-specific while restaurants, shops,
museums and medical places need the same information. The association fields
that could tie these together are inconsistently named: `GeoPlaceCategory.classifier`,
`ExternalLink.link_type`.

The existing `Category` model already provides a hierarchy with slugs, ordering
and translations — it can define relation semantics without a new relation-type
model.

Source: `_work/260313_geoplace_feature_graph_spec.md` (concept) and
`_work/260313_feature_graph_implementation.md` (implementation plan, incl. a
2026-03-13 code review of 17 affected files across 5 tiers).

## Goals / Non-Goals

**Goals:**

- Semantic relations between GeoPlaces with fast, index-backed queries (no
  spatial operations for hierarchy/context lookups).
- One consistent `relation` field name across `GeoPlaceCategory`,
  `ExternalLink` and the new models.
- Generic operating modes (`GeoPlaceOperation`) for every place type,
  replacing `AmenityDetail` completely.
- Month availability as DB-validated 0–100 integers with a clean Python API
  (`Month` enum, `MonthAccessor`).
- Deterministic migration path including data migrations (parent → relations,
  AmenityDetail → GeoPlaceOperation).

**Non-Goals:**

- Routes (`RouteRelation`, ordered nodes, LineString) — separate future change.
- Organization migration onto the Category system (`owned_by` relations) —
  Phase 2 per the implementation plan.
- `inverse_relation` on Category — reverse queries swap `from_place`/`to_place`;
  a display-only reverse category can be added later if a UI needs it.
- Hierarchical grouping under `relations/` (spatial/, infrastructure/) — only
  if query patterns eventually require it.

## Decisions

### D1: Category as the relation-type model

Relation types are `Category` rows under a `relations/` parent
(`part_of`, `near`, `serves`, `access_point`). No new RelationType model.
*Rationale*: Category already has hierarchy, slugs, ordering, i18n and admin
support; a parallel model would duplicate all of it.

### D2: One-direction storage, no inverse_relation

Each edge is stored once; reverse queries swap the FK direction
(`outgoing_relations` vs `incoming_relations` related names). An
`inverse_relation` field on Category is explicitly rejected (keep semantics
simple; add a display-only reverse category later if needed).

### D3: Months as twelve integer columns (0–100)

`month_01`…`month_12` `PositiveSmallIntegerField` with `MaxValueValidator(100)`,
nullable = unknown. A 1-based `Month` IntEnum plus a dict-like `MonthAccessor`
(`op.months[Month.JULY] = 100`) provides the ergonomic API.
*Rationale*: per-column ints are indexable (`month_07`, `month_12` indexes for
summer/winter queries), DB-validated, and avoid JSON array scanning. The
fuzzy-string values (`no`/`noish`/`maybe`/`yesish`/`yes`) map deterministically
to 0/25/50/75/100 during migration.

### D4: GeoPlaceOperation is generic, AmenityDetail is deleted

One model for all place types: nullable `capacity` (beds/seats/visitors by
type), `hours` as a plain OSM-compatible string (display-only, not queried),
`extra` JSONB for structured details (staffed, services, price). It links to
`GeoPlaceCategory.relation` (under `service/`: standard, reduced) so categories
and operating modes stay consistent. Phones become `ExternalLink` rows with
`tel:` URIs.

### D5: GeoPlace.parent is removed

Hierarchy is expressed exclusively through `part_of` relations
(`hut.add_relation(municipality, "part_of")`). A data-migration management
command (`migrate_parent_to_relations`) converts existing parent links first.
*Rationale*: two parallel hierarchy mechanisms invite drift; the graph is the
single source of truth.

### D6: Unified `relation` naming

`GeoPlaceCategory.classifier` → `relation`, `ExternalLink.link_type` →
`relation` — renames in models, schemas, API fields, admin and imports.

### D7: Migration order is strict

(1) field renames, (2) new models, (3) category fixtures, (4) code reference
updates, (5) `migrate_parent_to_relations`, (6) remove `parent`, (7)
`migrate_amenity_to_operation`, (8) delete `AmenityDetail`. Renames first
avoids FK violations; data migrations run before their source models disappear.

## Risks / Trade-offs

- [BREAKING API field renames (`classifier`, `link_type`) and removed
  AmenityDetail schema] → coordinate with frontend consumers; the change rides
  a major-version API boundary.
- [OSM import is heavily coupled to AmenityDetail] → import updated in the same
  change (AmenityDetailInput → GeoPlaceOperationInput, Month enum usage);
  verified by the import test suite.
- [Migration ordering mistakes cause FK violations] → the task list encodes the
  exact order; verification greps for stale references afterwards.
- [Losing fuzzy month nuance (yes/noish/…)] → deterministic 25-step mapping
  documented in the migration helper.

## Migration Plan

Follows D7's eight phases; two new management commands
(`migrate_parent_to_relations`, `migrate_amenity_to_operation`), six
Django migrations. Rollback: keep the rename migrations reversible; the data
migrations are forward-only (source data deleted afterwards by design).

## Open Questions

- Should `relation/located_in` be distinguished from `part_of`? Deferred —
  add when a concrete requirement appears (per implementation plan Phase 1+).
- Emergency service mode (`service/emergency`): listed as future extension;
  add on demand.
