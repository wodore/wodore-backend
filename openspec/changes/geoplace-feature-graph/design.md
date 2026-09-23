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

**Strategic sequencing (confirmed)**: GeoPlace is the strategic, more flexible
entity; `Hut` is the currently used model and will converge onto GeoPlace in a
**later, separate change**. This change builds all capabilities GeoPlace needs
first — so the graph ships with infrastructure value (imports, admin, internal
queries) even before the Hut convergence unlocks its headline queries.

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

- **Hut → GeoPlace convergence** — separate future change (sequencing above);
  the `migrate_hut_to_geoplace` sketch in the source documents belongs to that
  change, not this one.
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

### D1b: Canonical category slugs

The source documents used `service/`/`link/` in prose but `operating`/`link_types`
in all code blocks (`limit_choices_to=parent__slug="operating"` etc.). The
canonical slugs are **`relations/`, `operating/`, `link_types/`, `brand/`**
(code-consistent); the prose variants are normalized away in this change.

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

### D8: Auto-relation lifecycle and bounding

Auto-generated edges carry `confidence < 1.0`; re-imports are idempotent —
an auto edge with the same `(from, to, relation)` triple is updated in place,
never duplicated, and curated edges (`confidence = 1.0`) are preserved.
Generation is bounded to defined place types (not the full GeoNames/OSM corpus)
to keep edge volume proportional to query needs. Without this, re-imports
would either duplicate (blocked by the unique triple) or strand stale edges
when geometries change.

### D10: Capacity is the accommodation function, one per operating mode
(RESOLVED — the original `unique(geo_place, relation)` constraint is kept)

Code evidence: multiple categories per place are the existing, working design
(`GeoPlaceCategory` is unique on `(place, category)`; the OSM import attaches
a *list* of category slugs per element; the category tree separates
accommodation types under `HUTS_CATEGORY_PARENT` from root-level categories
like `restaurant`). A hut-with-restaurant genuinely is both — "either/or"
would discard real OSM data.

The capacity ambiguity dissolves at the domain level: capacity means *beds of
the accommodation function*, and per operating mode a place has exactly one
accommodation type (the `hut_type_open` / `hut_type_closed` dichotomy becomes
`standard` / `reduced`). Non-accommodation categories (restaurant, toilet,
shower) never carry capacity — seats or similar, if ever needed, live in
`extra`. So `unique(geo_place, relation)` holds: one operational profile
(capacity, months, hours) per place per mode.

### D9: Fixtures reconcile with existing DB categories

The categories app has no fixtures today, but relation/link-type parents may
already exist as admin-created rows in environments. The `relation_categories`
fixture therefore uses get-or-create semantics keyed on slug, so loading is
idempotent against both fresh and pre-populated databases.

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

- **API compatibility policy (decision needed)** — the `classifier`/`link_type`
  renames and the AmenityDetail→Operation schema are BREAKING for API
  consumers (frontend). Options: hard cut on the next API version, or a
  transitional dual-field serialization. Needs frontend coordination.
- Should `relation/located_in` be distinguished from `part_of`? Deferred —
  add when a concrete requirement appears (per implementation plan Phase 1+).
- Emergency operating mode (`operating/emergency`): listed as future
  extension; add on demand.
