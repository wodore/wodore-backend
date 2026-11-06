# place-visit-counter Specification

## Purpose
Best-effort, aggregated visit counting for huts and GeoPlaces: detail-endpoint hooks with visitor dedup, cache-buffered asynchronous writes, daily per-object storage via contenttypes, and internal (admin) consumption of popularity aggregates. Counts are approximate popularity signals, not analytics; no PII is stored.
## Requirements
### Requirement: Best-effort visit counting with visitor dedup
The system SHALL count visits per object per day, incremented when a hut
or place detail endpoint serves a page request, at most once per visitor
per object within a short dedup window (opaque visitor key derived from
request properties, kept only in the cache). Counting SHALL NOT add a
database write to the request path; increments are buffered in the cache
and flushed asynchronously. Requests with `update_cache=true` SHALL NOT
be counted, nor requests from a short static prefetch/crawler
user-agent list. Counting failures SHALL NOT affect the observed
response. The images endpoints SHALL NOT be counted (they stay
response-cacheable; the detail fetch is the page-view signal).

#### Scenario: Hut page visit is counted

- **WHEN** a visitor loads a hut page (hut detail endpoint hit for an existing hut)
- **THEN** the hut's daily counter is incremented via the async buffer and the response is served normally

#### Scenario: Repeat fetches within the window count once

- **WHEN** the same visitor hits the detail endpoint for the same place several times within the dedup window
- **THEN** the place's counter is incremented exactly once for that window

#### Scenario: Operator refresh is not counted

- **WHEN** counting observes a request with `update_cache=true` or a prefetch user agent
- **THEN** no visit is counted

### Requirement: Generic daily counter storage
Visits SHALL be stored as one row per `(content_type, object_id, day)`
with a count, attached via Django contenttypes (GenericForeignKey),
uniquely constrained, with an index supporting top-N-per-day queries. The
model SHALL use the project's TimeStampedModel (created/modified) for row
debugging. The counter SHALL work for any model without schema changes.
Rows SHALL NOT reference counted objects by hard foreign key (counters
outlive them).

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
helper (top places by visit sum over a configurable window) and sortable
visit columns in the Hut and GeoPlace admins (30-day and one-year
windows, SQL-side subquery annotations). Counts SHALL NOT be exposed
through public API endpoints in this change.

#### Scenario: Admin sorts by visits

- **WHEN** an admin sorts the Hut changelist by a visits column
- **THEN** huts are ordered by their visit aggregate for that column's window
