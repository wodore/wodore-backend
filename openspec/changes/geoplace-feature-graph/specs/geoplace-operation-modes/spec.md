## ADDED Requirements

### Requirement: GeoPlaceOperation generic operating-mode model
The system SHALL provide a `GeoPlaceOperation` model linking a GeoPlace to an `operating/` Category (standard, reduced) with: nullable `capacity` (semantics per place type — beds/seats/visitors), a free-text `hours` string (OSM-compatible or custom, display-only), an `extra` JSON field, and `is_active`, unique per `(geo_place, relation)`.

#### Scenario: Capacity semantics per type
- **WHEN** a hut has `capacity=170` on a standard operation and a restaurant has `capacity=40`
- **THEN** both are stored in the same nullable capacity field without type-specific columns

#### Scenario: Unique per place and mode
- **WHEN** two operations with the same `(geo_place, relation)` are created
- **THEN** the second insert is rejected

### Requirement: Month availability as validated integers
Month availability SHALL be stored as twelve `month_01`…`month_12` integer columns with values 0–100 (opening percentage; NULL = unknown), each DB-validated to at most 100, with indexes on `month_07` and `month_12` for seasonal queries.

#### Scenario: Seasonal query
- **WHEN** querying `GeoPlace.objects.filter(operations__month_07__gte=75)`
- **THEN** all places at least 75% open in July are returned using the month_07 index

#### Scenario: Out-of-range value rejected
- **WHEN** a month field is set above 100
- **THEN** validation rejects the value

### Requirement: Month enum and accessor API
The system SHALL provide a 1-based `Month` IntEnum (JANUARY=1 … DECEMBER=12) and a dict-like `MonthAccessor` exposing `op.months[Month.JULY] = 100`, `op.months[Month.JUNE]`, and `op.months.to_dict()`, raising TypeError for non-Month keys and ValueError for percentages outside 0–100.

#### Scenario: Accessor round-trip
- **WHEN** `op.months[Month.JULY] = 100` then `op.months[Month.JULY]` is read after refresh
- **THEN** the stored month_07 value is 100

#### Scenario: Invalid key type
- **WHEN** `op.months["jul"]` is used
- **THEN** a TypeError naming the Month enum is raised

### Requirement: AmenityDetail replaced
The system SHALL migrate all `AmenityDetail` data into `GeoPlaceOperation` via a `migrate_amenity_to_operation` management command and SHALL delete the `AmenityDetail` model, its schema, imports and admin references afterwards. Source shape (verified against the current code): `AmenityDetail.opening_months` is a JSON dict keyed by month names holding `MonthStatus` TextChoices values (yes/yesish/maybe/noish/no/unknown), mapped deterministically to no=0, noish=25, maybe=50, yesish=75, yes=100, unknown=NULL.

#### Scenario: Fuzzy month mapping
- **WHEN** migration encounters `open_monthly.jul = "yes"`
- **THEN** the resulting operation has `month_07 = 100`

#### Scenario: Model fully removed
- **WHEN** the final migration is applied and the codebase is searched
- **THEN** no `AmenityDetail` references remain in models, schemas, API, admin or imports
