# Geoplace Availability — Spec Delta

## ADDED Requirements

### Requirement: Per-place availability state

The system SHALL store current availability as one row per place per date on
`GeoPlaceAvailability`, enforced by `unique (geo_place, availability_date)`.
Each row SHALL carry free/total/free-tolerance, occupancy
(percent/steps/status), reservation status, the booking link, and the
type-of-the-day (open/closed) category. Source attribution
(`source_organization`, `source_id`) SHALL be stored on the row. Rows SHALL
be guarded by check constraints on the occupancy and reservation status
enums and indexed on `(geo_place, availability_date)` and
`(availability_date, last_checked)`.

#### Scenario: Single row per place and date

- **WHEN** availability is updated twice for the same place and date
- **THEN** the system updates the existing row in place instead of creating a
  second row

#### Scenario: Winter and summer are one stream

- **WHEN** a place's type-of-the-day changes from open to closed
- **THEN** the same `(geo_place, availability_date)` row is updated and the
  type-of-the-day column reflects the new category

### Requirement: Availability history with change detection

The system SHALL append a `GeoPlaceAvailabilityHistory` row only when the
availability values actually change, and SHALL update `last_checked` on the
current-state row and the latest history row otherwise. History rows SHALL
record first/last-checked timestamps so state durations are derivable.

#### Scenario: Changed availability is recorded

- **WHEN** a fetch returns different free/total/type/reservation values than
  the stored state
- **THEN** the system appends one history row with the new values and updates
  the current-state row

#### Scenario: Unchanged availability is not duplicated

- **WHEN** a fetch returns identical values to the stored state
- **THEN** no new history row is created and only `last_checked` is advanced

### Requirement: Per-place fetch bookkeeping

The system SHALL maintain a `GeoPlaceAvailabilityStatus` row per tracked
place recording last_checked, last_success, has_data, and
consecutive_failures, and the update cadence SHALL be driven by it.

#### Scenario: Failed fetch backs off

- **WHEN** a fetch for a place returns no data or errors
- **THEN** consecutive_failures is incremented and the place's update
  priority is deprioritized

### Requirement: Backfill current state from hut models

The system SHALL copy each hut's current availability into
`GeoPlaceAvailability` (including status bookkeeping) as a straight column
copy through the source association `(organization "wodore",
source_id = hut.slug)`, without recomputing or re-fetching. Huts without a
matching place SHALL be reported, not skipped silently.

#### Scenario: Hut with matching place is copied

- **WHEN** the backfill runs for a hut whose association resolves to a place
- **THEN** a `GeoPlaceAvailability` row exists per existing
  `HutAvailability` row with identical values

#### Scenario: Hut without matching place is reported

- **WHEN** the backfill encounters a hut with availability but no place
  association
- **THEN** the hut is listed in the backfill report and no place row is
  created for it

### Requirement: History move command

The system SHALL provide `move_availability_history` to move
`HutAvailabilityHistory` rows into `GeoPlaceAvailabilityHistory` as a
background, chunked task. The command SHALL be idempotent (re-running creates
no duplicates; natural key `(geo_place, availability_date, first_checked)`),
resumable after interruption, and support `--dry-run`.

#### Scenario: Re-running is a no-op

- **WHEN** the command completes and is run again
- **THEN** zero new history rows are created

#### Scenario: Interrupted run resumes

- **WHEN** a run is interrupted and restarted
- **THEN** previously moved rows are not duplicated and the run continues
  from where it stopped

### Requirement: Update pipeline writes place tables

The availability update pipeline SHALL write the GeoPlace availability
tables through the source association while hut readers still exist
(pipeline entry points: `AvailabilityService`, `update_availability`), and
SHALL keep hut-table and place-table content identical during that window.

#### Scenario: Update lands on the place

- **WHEN** `update_availability` processes a hut whose association resolves
  to a place
- **THEN** the place's current state, history (on change), and status rows
  reflect the update

### Requirement: Readers serve from place tables unchanged

After cutover, readers SHALL serve availability from the GeoPlace tables:
the martin `availability` tile function and the availability API
controllers for the GeoJSON layer, current per-hut state, and trend
history, plus admin read surfaces — with response and tile shapes identical
to the hut-table reads they replace.

#### Scenario: Tile properties are identical

- **WHEN** the same availability tile is requested before and after cutover
  for unchanged data
- **THEN** the feature properties (`slug`, `dN_*`, `capacity`, `days`) are
  identical

#### Scenario: Availability endpoint contracts are stable

- **WHEN** the current-availability or trend endpoints are called before and
  after cutover for unchanged data
- **THEN** the response bodies and ETag behavior are unchanged and no API
  version transition is required

#### Scenario: Source link stays populated

- **WHEN** the current-availability endpoint responds after cutover
- **THEN** `source_link` is populated exactly as before, via the retained
  hut-side association lookup until the final phase

### Requirement: Hut availability models are removed

After the reader cutover is verified, the system SHALL remove
`AvailabilityStatus`, `HutAvailability`, `HutAvailabilityHistory`, their
admin surfaces, and the old write path. Removal SHALL be gated on the
backfill unmatched report being empty.

#### Scenario: No hut availability tables remain

- **WHEN** the final phase is deployed
- **THEN** no hut-keyed availability model, table, or ORM reference remains
  in the codebase
