## ADDED Requirements

### Requirement: Best-effort visit counting on hut detail views
The system SHALL count visits per hut per day, incremented when the hut
images endpoint serves a hut page request. Counting SHALL NOT add a
database write to the request path; increments are buffered in the cache
and flushed asynchronously. Requests with `update_cache=true` SHALL NOT be
counted. Counting failures SHALL NOT affect the observed response.

#### Scenario: Hut page visit is counted

- **WHEN** a visitor loads a hut page (images endpoint hit for an existing hut)
- **THEN** the hut's daily counter is incremented via the async buffer and the response is served normally

#### Scenario: Operator refresh is not counted

- **WHEN** the images endpoint is called with `update_cache=true`
- **THEN** no visit is counted

### Requirement: Daily aggregated counter storage
Visits SHALL be stored as one row per `(place_type, place_id, day)` with a
count, uniquely constrained, with an index supporting top-N-per-day
queries. Rows SHALL NOT reference places by foreign key (counters outlive
their places).

#### Scenario: Flush aggregates the buffer

- **WHEN** the flush task runs with buffered counters for a hut
- **THEN** a single row per (hut, day) is upserted with the buffered total, not one row per visit

### Requirement: Cache-batched asynchronous flush
Buffered counters SHALL be flushed to storage by a background task when a
place's buffer crosses a small threshold or on its first buffered visit.
The flush SHALL read-and-clear the buffer atomically per key. Worker
restarts MAY lose buffered counts (best-effort, documented).

#### Scenario: Popular place flushes without hot-path writes

- **WHEN** a hut receives repeated visits
- **THEN** the request path performs no counter database writes and at most one flush task is enqueued per place per threshold crossing

### Requirement: Popularity consumption
The system SHALL expose visit aggregates internally: a `popular_places`
helper (top places by visit sum over a configurable window) and a sortable
recent-visits column in the Hut and GeoPlace admins. The image sync
command's `--all` sweep SHALL support `--popular-first` ordering by recent
visit sums. Counts SHALL NOT be exposed through public API endpoints in
this change.

#### Scenario: Sweep orders by popularity

- **WHEN** `geoimages_pin --all --popular-first` runs
- **THEN** sweep targets are ordered by descending visit sum over the recent window, places without counters sorted last

#### Scenario: Admin sorts by visits

- **WHEN** an admin sorts the Hut changelist by the visits column
- **THEN** huts are ordered by their recent visit aggregate
