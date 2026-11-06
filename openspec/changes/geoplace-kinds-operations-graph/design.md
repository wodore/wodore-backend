# Design: geoplace-kinds-operations-graph

## Context

Supersedes draft PR #154 (`geoplace-feature-graph`) and builds on the
shipped association machinery (PR #446: mode classifiers +
schema-validated association `extra` + `CategoryExtraSchema`).
Discussion history: two Opus advisor rounds (grain correction —
place-level vs association-level facts; derive-but-store `detail_type`
because tiles SQL reads it; no primary-category flag exists) and PO
decisions (extras vs typed columns settled as *both layers*; opening
months are global with mode semantics; drop + re-import is acceptable
— GeoPlace is not in production use). A third advisor round reviewed
this draft (verdict: ready after fixes — all applied; see tasks).

**Sequencing: PR #446 merges as-is first.** It is the foundation this
change assumes (mode vocabulary, CategoryExtraSchema, jedison admin,
wodore import on the schema path); the only churn is capacity's home
(one key, `association.extra.capacity` → `operation.capacity`),
erased by drop + re-import. This change then retires the `capacity`
key from the accommodation extra schema and mirrors operation
capacity into the tiles view — the two bits of #446 it unwinds.

## Goals / Non-Goals

**Goals:** finalize the GeoPlace data model so the Hut migration (next
change) has a complete target; kinds, typed operation facts,
seasonality, relation graph; detail models gone.

**Non-Goals:** the Hut→GeoPlace data migration; availability Phase D/E;
transport schedules (may deserve a real query-shaped table later);
renaming `classifier`/`uri_kind`.

## Decisions

1. **Both layers: typed facts + flexible classification.** The
   extras-vs-details debate resolves as *both*: well-known structured
   facts (capacity, hours, months) get typed columns on dedicated rows
   (DB constraints, safe ALTER migrations, indexable); unknown future
   attributes keep the schema-validated association `extra`
   (admin-editable, forward-compatible). Rule: stable + shared shape +
   constrainable → typed; sparse + heterogeneous + unknown → extra.

2. **Kind = category root parent; contract in code.** `PLACE_KINDS`
   registry (geometries/kinds.py) maps root parent slugs →
   `(detail_type, allowed classifier subtrees)`, pinned to the live
   root tree (see the spec's mapping table — accommodation/groceries/
   sport/… → amenity; transport → transport; administrative/
   populated_place → admin; terrain/hydrographic → natural; default
   amenity). Vocabulary roots (mode, role, relations, external_link,
   link_type) are excluded from kind resolution. Registry values are
   asserted ⊆ the `detail_type` CHECK constraint set
   (amenity/transport/admin/natural/none). The category tree is the
   taxonomy; roots double as overlay groups. No marker association —
   the anchoring category *is* the kind; tie-break: parent of the
   first category by `(order, slug)`. `detail_type` is **derived on
   write, stored** (raw SQL in tile/clustering migrations reads the
   column). Structure lives in code, data schemas in the DB.

3. **`GeoPlaceOperation`**: `(geo_place, mode)` unique, `capacity`
   nullable int ≥ 0 (CHECK; semantics per kind), `opening_hours`
   structured JSON (per-mode hours become possible), `extra` JSONB
   overflow. Invariant: capacity is **per-mode, not
   per-category-per-mode** — imports never emit two same-mode
   associations with differing capacities. Capacity moves here from
   association extra; the `capacity` key is removed from the seeded
   accommodation schema (no second home), and the tiles view keeps
   capacity visible by joining operation rows per mode. The mode
   vocabulary is shared with the association classifier.

4. **Seasonality = monthly standard share, place-level.** One value
   per month (0–100, NULL unknown) encodes which mode operates: 100 =
   only standard, 0 = only reduced, intermediate = temporal split
   within the month (not confidence). **Fully-closed is expressed via
   the reduced mode's category**: a hut whose reduced association is
   `accommodation.closed` is closed when share = 0; consistency rule
   (PO confirmed): a below-100 month with **no reduced type resolves
   the reduced mode to `accommodation.unknown`** — materialized as
   an association (matching the capacity rule) or left implicit;
   the share value stands, never NULL-coerced. Stored
   as twelve int columns on a OneToOne `GeoPlaceSeasonality` row
   (only where data exists), CHECK-constrained; `Month` IntEnum +
   `MonthAccessor` ported from #154. Fuzzy mapping:
   `yes=100, yesish=75, maybe=50, noish=25, no=0, unknown=NULL`.
   Future `dN_type` source.

5. **Relation graph from #154, adopted as specified**: `relations/*`
   vocabulary, one-direction edges, unique triple, no self-loops,
   confidence + extra, composite indexes, helpers, `GeoPlace.parent`
   removed via data migration to `part_of`. Parent removal is
   output-wire-neutral (verified — no API payload serialized `parent`)
   but drops the input-schema `parent_id` (changelog note) and must
   clean two easy-to-miss spots: `providers/base.py`
   `select_related("parent")` and the `simple_fields` entry in
   `_track_field_modifications`. Auto-generation hooks (containment →
   part_of, proximity → serves, confidence < 1.0, idempotent,
   type-bounded) with configurable thresholds.

6. **Protected vocabulary**: `Category.is_protected` (bool, default
   false). Seeded on: mode.*, role.*, relations.*, root kind parents,
   uri-kind roots. Admin blocks deletion (RESTRICT covers in-use;
   this covers not-yet-used rows); names/colors/symbols stay
   editable — code couples to slugs only.

7. **Detail retirement + booking + place-level extra.** AmenityDetail
   deleted (hours → operation rows; `operating_status` not migrated —
   reads default to `open`, preserving the wire shape; months →
   seasonality). AdminDetail deleted (population/postal_code/
   iso_code → `GeoPlace.extra`). **Place-level extra validation is a
   new mechanism**: `resolve_extra_schema` gains place-level
   resolution (kind root parent, overridable by an explicit schema
   row) wired into the same write paths and guardrails as association
   extra; the admin renders place extra through the same JSON-Schema
   widget. Booking = `uri.booking` ExternalLink +
   `GeoPlaceSourceAssociation` + optional party `role.source`;
   `is_bookable` derived, never stored. The API amenity block keeps
   its wire shape, served from the new homes.

8. **No renames.** #154's `unified-relation-naming` is obsolete:
   `link_type` already became `uri_kind` (external-link-uris), and
   renaming the just-shipped `classifier` is churn without gain.

## Risks / Trade-offs

- [Months as columns vs JSONB] → columns for CHECK constraints and
  seasonal filter ergonomics (#154 rationale), on a separate row so
  GeoPlace stays lean; expression-index a month only when a filter
  ships.
- [`parent` removal is breaking] → accepted: output-wire-neutral
  (verified), input `parent_id` drops with a changelog note; drop +
  re-import is the migration path.
- [Three extra/fact homes (place extra, association extra, operation
  row)] → each has one rule (place-level attributes / classification
  overflow / typed mode facts), documented per spec; validation
  messages name the target.
- [Seasonality closed-semantics] → PO confirmed: 0 = the reduced
  mode operates, whatever its category (self-service, winter room,
  or closed — mirroring today's hut behavior); months below 100
  without a reduced type resolve to `accommodation.unknown`
  (explicit association or implicit absent-mode), never NULL-coerced.

## Migration Plan

GeoPlace data is disposable (drop + re-import allowed) — but the plan
stays reversible per-model:

1. Schema: `Category.is_protected`; new models (GeoPlaceOperation,
   GeoPlaceSeasonality, GeoPlaceRelation); seeds (relations vocab,
   protected marking, kind schemas, place-level schemas).
2. Write path: detail_type derived-on-write; operation/seasonality
   upserts in `GeoPlace.update_or_create` (protected-fields policy
   applies); place-level extra validation wired; imports retargeted
   (OSM hours/months + wodore capacity/months).
3. Readers: API amenity block from operation rows; tiles keep
   capacity via the operation join; admin inlines (operation,
   seasonality); kind-aware classifier autocomplete.
4. Retirement: capacity key dropped from the accommodation extra
   schema; AmenityDetail/AdminDetail deletion migrations; then
   `parent` → `part_of` data migration + field removal + the two
   named cleanup spots.
5. Full re-import on dev/staging; verification (counts, spot-checks).

## Open Questions

- Seasonality closed-semantics confirmation (D4) — PO pending.
- `opening_hours` weekly-schema JSON vs OSM syntax string (current
  shape wins — structured, translatable).
- Auto-generation thresholds — configure during implementation.

## Follow-ups (separate changes)

- **Hut → GeoPlace data migration** (the immediate next change; now
  has a complete target model).
- Availability Phase D/E (`dN_type` from seasonality/classifiers).
- Contacts removal (unchanged gating).
