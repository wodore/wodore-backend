# Spec Delta: geoplace-seasonality

## ADDED Requirements

### Requirement: Monthly standard share

The system SHALL provide a `GeoPlaceSeasonality` model (OneToOne per
GeoPlace, rows only where data exists) with twelve integer columns
`month_01…month_12`, each NULL (unknown) or 0–100 (DB-checked). The
value is the **standard share** for that month: `100` = only the
standard mode operates, `0` = only the reduced mode, values between =
a temporal split within the month (75 = three quarters of the month
in standard mode — NOT a confidence value). The "modes must sum to
100%" rule is inherent to the single-value encoding.

**"Fully closed" rides on the reduced mode's category, not a third
value** (PO confirmed): `0` means the reduced association operates —
and when that association's category is `accommodation.closed`, the
reduced operation *is* closedness. **A below-100 month with no
reduced type resolves the reduced mode to `accommodation.unknown`**
— importers either materialize the `(accommodation.unknown,
mode.reduced)` association (consistent with the capacity rule) or
leave it implicit (absent reduced mode reads as unknown type). The
share value stands either way — never coerced to NULL.

#### Scenario: Summer hut, winter room
- **WHEN** a staffed hut operates July–October and is a winter room
  the rest of the year
- **THEN** its seasonality row carries `100` for months 07–10 and `0`
  for the others

#### Scenario: Fully closed winter maps to the closed reduced mode
- **WHEN** a hut's reduced-mode association has category
  `accommodation.closed` and `open_monthly.dec = no`
- **THEN** `month_12 = 0` — reduced (closed) operates in December

#### Scenario: Below-100 month without a reduced type resolves to unknown
- **WHEN** a hut publishes `open_monthly.dec = no` but has no
  reduced-mode association
- **THEN** `month_12 = 0` and the reduced mode is
  `accommodation.unknown` — materialized as a
  `(accommodation.unknown, mode.reduced)` association or left
  implicit; the share value stands

#### Scenario: Out-of-range rejected
- **WHEN** a month column is written with 150
- **THEN** the check constraint rejects it

#### Scenario: Unknown stays unknown
- **WHEN** a month's status is unknown
- **THEN** the column is NULL — never coerced to 0 or 100

### Requirement: Fuzzy vocabulary mapping

Imports SHALL map the hut-services `open_monthly` fuzzy values
deterministically: `yes=100, yesish=75, maybe=50, noish=25, no=0,
unknown=NULL`.

#### Scenario: open_monthly mapping
- **WHEN** a hut publishes `jul: yes` and `dec: no`
- **THEN** `month_07=100` and `month_12=0`

### Requirement: Month accessor API

The system SHALL provide a 1-based `Month` IntEnum and a dict-like
`MonthAccessor` on `GeoPlaceSeasonality` (ported from #154):
`season.months[Month.JULY] = 100`, reads, and `to_dict()` round-trips,
raising `TypeError` for non-Month keys and `ValueError` outside
0–100 — raw numbered columns are never hand-indexed.

#### Scenario: Accessor round-trip
- **WHEN** `season.months[Month.JULY] = 100` is set and read after
  refresh
- **THEN** `month_07` stores 100 and the accessor returns it

### Requirement: Availability classification source

The system SHALL make the availability tiles' per-day standard/reduced
classification (`dN_type`) derivable from seasonality (date → month →
share) once availability Phase D adopts it — replacing the
`huts_hut` join in the tile SQL.

#### Scenario: Day classification from share
- **WHEN** a date falls in a month with share 100
- **THEN** the day classifies as `standard`
