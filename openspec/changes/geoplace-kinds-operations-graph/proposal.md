# Proposal: geoplace-kinds-operations-graph

## Why

GeoPlace is about to become the single place entity (the Hut migration
follows immediately after), but four gaps keep it from being
"final": the kind of a place exists only as the implicit
`detail_type` enum; structured operating facts (capacity, opening
hours) have no typed home (AmenityDetail is semantically empty — all
391k rows are `operating_status='open'`, phones/brand/urls already
migrated to links/parties); seasonality has no representation at all;
and hierarchy/context is a `parent` self-FK plus runtime spatial
operations. This change finalizes GeoPlace in one coherent step:
**kinds via the category taxonomy, typed operation facts, place-level
seasonality, and the semantic relation graph** — superseding the
draft PR #154 (`geoplace-feature-graph`, branch `geo_featuregraph`),
which proposed a subset of this before the classifier/schema machinery
(PR #446) existed.

GeoPlace is not yet in production use — data may be dropped and
re-imported, which this change exploits (no long dual-write phases).

## What Changes

- **Kinds from the taxonomy (code contract, derived `detail_type`)**:
  a `PLACE_KINDS` registry maps each root category parent
  (`accommodation`, `groceries`, `sport`, `transport`,
  `administrative`, …) to a contract — allowed classifier subtrees
  (e.g. `mode` for accommodation only) and the derived
  `detail_type`. `GeoPlace.detail_type` stays a stored column (tile +
  clustering SQL reads it) but is populated on write from the place's
  first category parent instead of being declared by every input
  schema. The admin classifier autocomplete scopes to the kind's
  allowed subtrees (generalizing the hardcoded `mode` scope).
- **`Category.is_protected`**: code-coupled vocabulary (mode.*, role.*,
  relations.*, kind roots, uri kinds) is protected from deletion;
  names, colors and symbols remain editable.
- **`GeoPlaceOperation`** (revived from #154, amended): typed
  operating facts per `(place, mode)` — nullable `capacity`
  (int ≥ 0; semantics per kind: beds/seats/visitors), structured
  `opening_hours` JSON (per-mode hours become possible), `extra`
  overflow. Unique per `(geo_place, mode)`. Capacity moves here from
  association `extra` (#446) — the association stays pure
  classification (category × classifier) plus its schema-validated
  `extra` as the flexible layer for unknown future attributes.
- **`GeoPlaceSeasonality`**: place-level monthly operation as the
  **standard share** — twelve `month_01…month_12` int columns
  (0–100, NULL = unknown, CHECK-constrained). `100` = only standard
  mode operates, `0` = only reduced, values between = split; the
  "modes must sum to 100%" rule is inherent to the single value. One
  row per place (OneToOne, only where data exists); fuzzy vocabulary
  from hut-services maps deterministically (`yes=100, yesish=75,
  maybe=50, noish=25, no=0, unknown=NULL`). This is also the
  availability `dN_type` classification source (date → month → share
  → standard/reduced) — no `huts_hut` join.
- **`GeoPlaceRelation` graph** (from #154): one-direction semantic
  edges typed by `relations/*` categories (`part_of`, `near`,
  `serves`, `access_point`), unique `(from, to, relation)`, no
  self-loops, `confidence` + `extra`, indexed traversal, `add_relation`
  / `get_related_places` helpers. **`GeoPlace.parent` is removed** —
  hierarchy is `part_of` edges (data migration; re-import acceptable).
  Import auto-generation hooks: containment → `part_of`, proximity →
  `serves` (confidence < 1.0, idempotent, bounded to configured types).
- **Detail models retired**: `AmenityDetail` and `AdminDetail` are
  deleted. Opening hours → `GeoPlaceOperation`; admin scalars
  (`population`, `postal_code`, `iso_code`) → `GeoPlace.extra`
  validated by the `administrative` kind schema. Booking attribution =
  `uri.booking` ExternalLink + `GeoPlaceSourceAssociation` (source,
  source_id — already the availability join) + optional party
  `role.source`; `is_bookable` is derived, never stored.
- **No renames**: `classifier` and `uri_kind` keep their names (the
  #154 `unified-relation-naming` rename is obsolete — `link_type`
  already became `uri_kind`, and renaming the just-shipped
  `classifier` is churn without gain; the unification is a documented
  convention: category-typed association fields).
- **Imports retargeted** (drop + re-import): OSM import writes hours →
  `GeoPlaceOperation`, months → seasonality (fuzzy mapping); the
  wodore hut import writes capacity → operation rows per mode.

## Capabilities

### New Capabilities

- `geoplace-kinds`: kind registry, derived-on-write `detail_type`,
  protected categories
- `geoplace-operations`: `GeoPlaceOperation` model (capacity, hours)
- `geoplace-seasonality`: monthly standard-share columns and semantics
- `geoplace-feature-graph`: `GeoPlaceRelation` model, helpers, parent
  removal, import auto-generation (adapted from #154)
- `geoplace-detail-retirement`: AmenityDetail/AdminDetail removal,
  data mapping, booking attribution

### Modified Capabilities

(none — `geoplace-category-attributes` (#446) stays as shipped; the
capacity move from association extra to operation rows is additive to
that spec via this change's deltas)

## Impact

- **Models/migrations**: `geometries` (Category flag via `categories`,
  GeoPlaceOperation, GeoPlaceSeasonality, GeoPlaceRelation,
  parent-field removal, detail deletions), new seed migrations
  (relations vocabulary, protected marking, kind schemas)
- **Write paths**: `GeoPlace.update_or_create` (+ detail_type
  derivation, operation upsert, seasonality upsert), OSM import,
  wodore import
- **Readers**: API amenity block served from operation/extra (wire
  shape preserved), tiles (detail_type stays; months optionally join
  later), admin (kind-aware autocomplete, seasonality/operation
  inlines)
- **Supersedes**: PR #154 (`geoplace-feature-graph` openspec) — its
  operation/mode and naming specs are absorbed/amended here; the graph
  spec is adopted with the same semantics
- **Out of scope**: the Hut → GeoPlace data migration itself (next
  change), availability Phase D/E (separate), transport schedules (a
  real detail table may return for them if ever query-heavy)
