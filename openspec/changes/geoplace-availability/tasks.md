# Geoplace Availability — Tasks

## 1. Models & schema (Phase A)

- [ ] 1.1 Add `GeoPlaceAvailability` (fields/constraints per spec, port of
  `HutAvailability`; attribution columns unchanged; check constraints on
  occupancy/reservation enums; indexes `(geo_place, availability_date)` and
  `(availability_date, last_checked)`; `hut_type` FK keeps its
  `limit_choices_to` filter) + manager port (`for_date_range`,
  needing-update query surface)
- [ ] 1.2 Add `GeoPlaceAvailabilityHistory` (FK availability SET_NULL, FK
  geo_place CASCADE, snapshot fields, durations; check constraints on
  occupancy/reservation enums; index `(geo_place, availability_date,
  first_checked)`; `hut_type` FK keeps its `limit_choices_to` filter) +
  `for_trend` manager port
- [ ] 1.3 Add `GeoPlaceAvailabilityStatus` (OneToOne place with
  `primary_key=True`, fetch health fields, mark_success/mark_failure,
  `-last_checked` ordering)
- [ ] 1.4 Port the change-detection design (`update_availability` /
  `record_change` / `has_changed`) onto the new models
- [ ] 1.5 Schema migration for all three models; `manage.py check` +
  `makemigrations --check` clean
- [ ] 1.6 Model factories + unit tests (uniqueness, change detection, status
  transitions, manager queries)

## 2. Backfill (Phase B)

- [ ] 2.1 Hut→place join helper: resolve a hut to its place via the source
  association `(organization "wodore", source_id = hut.slug)`; expose the
  unmatched-hut set
- [ ] 2.2 Data migration: straight copy of `HutAvailability` →
  `GeoPlaceAvailability` and `AvailabilityStatus` →
  `GeoPlaceAvailabilityStatus` through the join
- [ ] 2.3 `move_availability_history` command: idempotent (natural key
  `(geo_place, availability_date, first_checked)`), resumable (id-range
  cursor), chunked via django-q, `--dry-run`; never copies hut PKs, never
  orders by id
- [ ] 2.4 Backfill report listing unmatched huts (gate artifact for Phase E)
- [ ] 2.5 Tests: join resolution, copy fidelity (field-for-field), idempotent
  re-runs, interrupted-run resume, unmatched reporting

## 3. Write-path retarget (Phase C)

- [ ] 3.1 Retarget the `AvailabilityService` persistence edge to the
  GeoPlace availability tables (hut resolves to (place, source) via the join;
  fetch and schema-conversion layers untouched; carry over
  `_sanitize_negative_free` and the batch-size/statement-timeout constants
  verbatim)
- [ ] 3.2 Dual-write: keep hut tables and place tables identical during the
  transition window
- [ ] 3.3 Drive the update cadence from `GeoPlaceAvailabilityStatus` (port
  `get_huts_needing_update` semantics; unmatched huts are still discovered
  and fetched during the dual-write window — logged, not errored)
- [ ] 3.4 Integration tests: `update_availability` lands current state,
  history (on change only), and status on the place; hut rows stay in sync

## 4. Reader cutover (Phase D)

- [ ] 4.1 Martin `availability` function SQL reads the place tables (keeps
  joining `huts_hut` for the `dN_type` open/closed classification until
  Phase E); regenerate `martin_sync`; document/perform the edge tile-cache
  purge AND `TRUNCATE availability_tile_cache` at deploy
- [ ] 4.2 The three availability API controllers
  (`HutAvailabilityGeojsonController`, `HutAvailabilityCurrentController` —
  keeps the hut-side `source_link` lookup until Phase E — and
  `HutAvailabilityTrendController`) read the place tables; `etag_utils`
  follows; deprecated `huts/api/_booking.py` and `api/readers.py` are
  unaffected — no change
- [ ] 4.3 Admin read surfaces (availability/history/status) read the place
  tables; the Hut admin availability inline keeps reading hut models until
  Phase E
- [ ] 4.4 Contract tests pinning tile feature properties (`slug`, `dN_*`,
  `capacity`, `days`) and booking responses/ETags — identical before/after;
  the GeoJSON feature `id` stays hut-side until Phase E

## 5. Hut model removal (Phase E)

- [ ] 5.1 Gate check: backfill unmatched report empty and Phase D verified in
  prod; assess the GeoJSON feature `id` switch (hut id → place id) against
  the API versioning runbook
- [ ] 5.2 Removal migration + code cleanup: drop `AvailabilityStatus`,
  `HutAvailability`, `HutAvailabilityHistory`, admin surfaces, old write
  path, and the dual-write path
- [ ] 5.3 Full suite green; no hut-keyed availability ORM references remain
