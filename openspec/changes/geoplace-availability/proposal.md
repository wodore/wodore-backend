# Geoplace Availability

## Why

Availability data (current state, change history, fetch bookkeeping) lives in three
hut-coupled models (`AvailabilityStatus`, `HutAvailability`, `HutAvailabilityHistory`)
in the `availability` app, all FK'd to `huts.Hut`. The platform's place entity is
`GeoPlace` (geometries) — parties and capacities have already moved there, and the
hut→places convergence continues (full import spec is a later change). Availability
must hang off places so any place can carry booking data independently of the legacy
hut model and the hut availability models can eventually be removed.

## What Changes

- New models in the existing `availability` app, porting the proven triad 1:1:
  - `GeoPlaceAvailability` — current state, one row per place per date,
    `unique (geo_place, availability_date)`; winter/summer stays in the
    type-of-the-day column (open/closed), exactly as `HutAvailability` handles it
  - `GeoPlaceAvailabilityHistory` — append-only change log with
    first/last-checked durations (change-detection design ports unchanged:
    history row only on actual change, `last_checked` touch otherwise)
  - `GeoPlaceAvailabilityStatus` — per-place fetch health (last_checked,
    last_success, has_data, consecutive_failures) backing the update cadence
- Source attribution moves along unchanged (`source_organization` FK,
  `source_id`, booking `link`) — org→party migration is a deliberate separate
  follow-up change
- Backfill of existing hut data:
  - current state copied in a data migration (straight column copy, no recompute)
  - history moved by a new `move_availability_history` management command —
    idempotent, resumable, runs as background chunks (django-q), `--dry-run`
- Hut↔place join for both: through the existing source association recorded by
  `import_geoplaces` (`organization "wodore"`, `source_id = hut.slug`), NOT raw
  geoplace-slug equality; unmatched huts are logged, never skipped silently
- Write-path retarget: `AvailabilityService` + `update_availability` command
  write the place tables via the same join
- Reader cutover: martin `availability` tile function and the three
  availability API controllers (GeoJSON layer, current per-hut state,
  trend history) — response/tile shapes stay identical (no API version
  bump, no `api:` labels); the deprecated huts booking API makes live
  external calls and never reads the availability tables — unaffected
- Final step: removal of `AvailabilityStatus`, `HutAvailability`,
  `HutAvailabilityHistory` and their admin/inline surfaces

## Capabilities

### New Capabilities

- `geoplace-availability`: per-place availability state, history, and fetch
  bookkeeping — storage shape, invariants, backfill from hut models, and the
  reader/writer cutover that ends with the hut models' removal

### Modified Capabilities

(none — no existing spec covers availability or the huts booking endpoints;
API response shapes are pinned by design)

## Impact

- `server/apps/availability/` — models, managers, services, admin, tiles SQL,
  api, tests, migrations (bulk of the change)
- `server/apps/availability/api.py` — the three DB-reading controllers
  retarget: `HutAvailabilityGeojsonController`,
  `HutAvailabilityCurrentController` (incl. its `source_link` derivation),
  `HutAvailabilityTrendController`
- `server/apps/huts/` — `etag_utils`, forms, admin inline read-side
  retarget; the deprecated booking API (`api/_booking.py`) calls external
  services live and never reads the availability tables — unaffected;
  `Hut` model keeps its availability-source reference until the write path
  no longer needs it
- `server/apps/geometries/` — read-only use of the import source association
  as the hut→place join
- `martin_sync` — availability function SQL regeneration + edge cache purge
  at cutover
- django-q — history move task
- `apiversions` registry references — audit only (`api/readers.py` defines
  reader specs and does not query the availability models)
- Composes with `geoplace-capacity-and-types-via-categories` (capacities are
  structural via categories; availability free/total stays live per-date)
