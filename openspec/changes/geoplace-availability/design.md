# Geoplace Availability — Design

## Context

The `availability` app stores booking/availability data in three models FK'd to
`huts.Hut`: `AvailabilityStatus` (per-hut fetch health), `HutAvailability`
(current state, `unique (hut, availability_date)`), `HutAvailabilityHistory`
(append-only change log). The update pipeline (`AvailabilityService`,
`update_availability`) fetches via hut-services, applies change detection, and
writes all three. Readers: the martin `availability` tile function (per-feature `slug` + `dN_*`
day props, DB-cached in `availability_tile_cache` for 900 s) and the three
`availability/api.py` controllers — GeoJSON layer, current per-hut state
(with ETags), trend history. The deprecated huts booking API calls external
services live and never reads these tables; `api/readers.py` defines reader
specs and does not query them.

The platform's place entity is `GeoPlace` (geometries). Parties and capacities
have landed place-level; the hut→places convergence continues with a full
import spec as a later change. Availability is the main remaining hut-coupled
domain.

There is no hut→place FK. `import_geoplaces` records the correspondence as a
source association: `(organization "wodore", source_id = hut.slug)` → place.

## Goals / Non-Goals

**Goals:**

- Availability state, history, and fetch bookkeeping keyed by `GeoPlace`
- Lossless move of existing hut data (current state + full history)
- All readers (tiles, API, admin) served from place tables with byte-identical
  response/tile shapes — no API version bump
- Removal of the hut availability models at the end

**Non-Goals:**

- org→party attribution migration (separate follow-up change)
- The hut→places import spec itself (later change; this design only reads the
  association it already maintains)
- Multi-source availability aggregation per place (one stream per place, see D2)
- Recomputing derived fields during backfill — straight copy
- New place types, capacity semantics (that is
  `geoplace-capacity-and-types-via-categories`; they compose: capacities are
  structural, availability is live per-date)

## Decisions

### D1 — Anchor on `GeoPlace`, not `AmenityDetail`

Availability is a time series (one row per place per date). `AmenityDetail`
is a 1:1 static detail table built on `GeoPlaceDetailBase` trackable-fields
machinery — the wrong shape. Tile features and the parties/capacity changes
anchor place-level identity.

*Alternative considered:* hanging rows off `AmenityDetail` — rejected: fights
the detail-table design, complicates the tile join, and no amenity-level
availability semantics exist.

### D2 — Single stream per place: `unique (geo_place, availability_date)`

Same invariant as per-hut today (`unique (hut, date)`). Winter/summer is not
two streams: it is the type-of-the-day column (open/closed), exactly as
`HutAvailability` carries it. One place, one bookable stream, one row per
date.

*Alternative considered:* `unique (place, source, date)` + a picker for
multi-source places (hut + winter room as separate sources) — rejected: no
current need; if aggregation ever becomes real it is a write-time concern,
not a schema concern.

### D3 — Port the triad 1:1, including `AvailabilityStatus`

Three models, same fields, same change-detection design (history row only on
actual change, `last_checked` touch otherwise), same manager surfaces
(`needing_update`, `for_date_range`, `for_trend`). The status table is not
optional: the update cadence and failure back-off depend on it. Model
fidelity beyond the field list: check constraints on the occupancy and
reservation status enums (both models), composite indexes
`(geo_place, availability_date)` and `(availability_date, last_checked)` on
current state, `(geo_place, availability_date, first_checked)` on history,
`primary_key=True` on the status OneToOne, and the `hut_type` FK
`limit_choices_to` (HUTS_CATEGORY_PARENT) on both availability models.
Stay in the `availability` app — no new app, hut models are removed in the
final phase.

### D4 — Attribution columns move unchanged

`source_organization` FK, `source_id`, booking `link` port as-is (org→party
is a separate change). History keeps today's shape: FK `availability`
(SET_NULL) + FK `geo_place` (CASCADE) + snapshot fields; org is derivable
via the availability row, not duplicated.

### D5 — Hut↔place join via the existing source association

Join `HutAvailability.source → GeoPlace` through the association recorded by
`import_geoplaces` (`organization "wodore"`, `source_id = hut.slug`), not raw
`geoplace.slug == hut.slug` equality (not guaranteed). Huts without a
matching place are logged and reported — never skipped silently.

### D6 — Backfill split: data migration now, history as background task

Current state: straight column copy in a data migration through the D5 join
(no recompute, no fetch). History: new `move_availability_history` command —
idempotent (natural-key dedupe), resumable (id-range cursor), chunked via
django-q, `--dry-run`. Speed does not matter; volume is hut-rows × change
events. Status rows are backfilled in the data migration too (preserves
last_checked/last_success/consecutive_failures so the cadence does not
reset).

History move rules (id and ordering): never copy hut PKs — fresh
auto-increment ids that carry no meaning; never order or filter history by
id — ordering is exclusively `(availability_date, first_checked)` with the
composite index as sort key; dedupe by natural key
`(geo_place, availability_date, first_checked)`, so out-of-order inserts
(backfill chunks landing after live dual-write rows) are always safe. If
Phase C deploys while the history move still runs, the same change event may
arrive from both paths with identical values and `first_checked` and
collapses via the natural key. Accepted residual risk: two real events for
the same (place, date) within one clock instant would dedupe to one —
impossible at the current per-hut serialized update cadence. UUID PKs were
considered and rejected: no house precedent, no distributed-ID problem to
solve (ids are never copied), and wider indexes on the highest-volume table
for no benefit — history row ids are never externally exposed.

### D7 — Phased rollout with dual-write window

- **A** — new models + migrations, inert
- **B** — backfill (data migration + `move_availability_history`)
- **C** — write-path retarget: `update_availability` writes the place tables
  via D5; **dual-writes** both hut and place tables so hut readers stay fresh
- **D** — reader cutover: martin availability function SQL and the three
  `availability/api.py` controllers (Geojson, Current, Trend) → place tables;
  admin read surfaces follow. Deploy includes `martin_sync` regen, edge tile
  cache purge, and `TRUNCATE availability_tile_cache` (the DB-level cache
  inside the function would serve pre-cutover data for up to 900 s).
  Shapes byte-identical (no `api:` labels, no Api-Version)
- **E** — drop hut availability models + admin surfaces + old write path

Two Phase D readers keep a temporary hut-side dependency until E (by design):
`HutAvailabilityCurrentController` keeps fetching the `Hut` by slug for its
`source_link` derivation (`HutOrganizationAssociation.link` — the place-side
association has no `link` field), and the tile SQL keeps joining `huts_hut`
for the `dN_type` standard/reduced classification (`hut_type_open_id` /
`hut_type_closed_id` — GeoPlace gains type FKs only via the separate capacity
change). The Hut admin availability inline likewise keeps reading hut models
until E — do not migrate it in D. Same for the GeoJSON controller's feature
`id` (`F("hut_id")` today): D keeps it hut-side via the reverse join for
byte-identical output; switching it to the place id happens at E and MUST
be assessed against the API versioning runbook then (value change for
clients keying features by id).

Each phase is independently deployable and reversible (E is irreversible but
gated on zero unmatched huts in the B report and D verified in prod).

*Alternative considered:* single cutover PR — rejected: reader blast radius
(tiles + booking API + ETags) deserves an isolated, verifiable flip.

### D8 — `AvailabilityTileCache` unchanged

Tile bookkeeping is keyed by tile coordinates and function params, not by the
underlying tables. It survives the move untouched.

## Risks / Trade-offs

- [Hut without matching place loses data continuity at E] → B produces an
  unmatched report; E is gated on it being empty (import/association fixed
  first); until then hut tables remain source of truth for those huts
- [Stale tiles after cutover] → D includes `martin_sync` regen and edge cache
  purge in the same deploy; the `?v=N` style bust applies
- [Drift between hut and place tables in the C→D window] → dual-write computes
  once, persists twice; drift impossible by construction, window kept short
- [History import long-running] → chunked, idempotent, resumable background
  task; reruns are cheap
- [Unmatched huts keep being fetched during the C→D window] → intentional:
  discovery still finds huts with `availability_source_ref` set; they are
  fetched, logged as unmatched, and hut-side rows stay authoritative for them
  until E
- [`AvailabilityService` is hut-centric (~1100 lines)] → retarget is
  mechanical (hut→(place, source) pair at the persistence edge); fetch and
  schema conversion layers are untouched; `_sanitize_negative_free` (DOC
  Tyler clamp) and the batch-size/statement-timeout constants carry over
  verbatim

## Migration Plan

Phases A–E above, one PR each (A–B may share a PR if both are small).
Rollback: A–D roll back by reverting the deploy (old tables/writers/readers
still intact until E). E lands only after D is verified in prod.

## Open Questions

None blocking. One note for the future hut→places import spec: preserving
`hut.slug` as the place slug would simplify future joins, but this change
does not depend on it (D5 already works today).
