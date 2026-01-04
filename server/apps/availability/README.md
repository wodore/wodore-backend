# Hut Availability Tracking App

This Django app tracks and stores historical hut availability/booking data from external sources.

## Overview

The app implements a two-table architecture:

1. **HutAvailability** - Current state table (one row per hut per date)
2. **HutAvailabilityHistory** - Append-only change log (records only when data changes)

## Models

### HutAvailability

Stores the current/latest availability state for fast retrieval.

**Key Fields (matching HutBookingSchema):**

- `free` - Number of available places
- `total` - Total number of places
- `occupancy_percent` - Occupancy percentage (0-100)
- `occupancy_steps` - Occupancy in discrete steps (0-100, increments of 10)
- `occupancy_status` - Status enum: empty, low, medium, high, full, unknown
- `reservation_status` - Status enum: unknown, possible, not_possible, not_online
- `link` - Booking URL
- `hut_type` - Hut type on this date (open/closed)
- `last_checked` - When this hut was last queried

**Relationships:**

- `hut` - FK to Hut model
- `source_organization` - FK to Organization model
- `source_hut_id` - ID in source organization's system

**Methods:**

- `has_changed(free, total)` - Check if data changed
- `record_change(free, total, **extra)` - Create history entry
- `update_availability(free, total, **extra)` - Update with change detection

### HutAvailabilityHistory

Append-only log of availability changes with state duration tracking.

**Key Fields (minimal storage for efficiency):**

- `free` - Number of available places
- `total` - Total number of places
- `occupancy_percent` - Occupancy percentage (for trend analysis)
- `hut_type` - Hut type on this date
- `first_checked` - When this state was first observed
- `last_checked` - When this state was last confirmed (updated on every check)

**Note:** Only essential fields are stored to minimize database size as this table can grow very large over time. Other computed fields (occupancy_steps, occupancy_status, reservation_status) can be derived from the current state table or recomputed from free/total if needed.

**Properties:**

- `duration_seconds` - How long this state lasted

## Managers

### HutAvailabilityManager

**Priority-based queries:**

- `needing_update()` - Returns huts needing updates based on occupancy and last check time
  - High priority (30 min): Full/nearly-full dates in next 14 days
  - Medium priority (3 hours): Moderate occupancy in next 14 days
  - Low priority (24 hours): Low occupancy in next 14 days

**View queries:**

- `for_map(date_from, date_to)` - Optimized for map view (default: next 4 days)
- `for_hut_detail(hut_id, date_from, date_to)` - Single hut query (default: next 14 days)
- `get_huts_needing_update()` - Returns distinct Hut objects needing updates

### HutAvailabilityHistoryManager

- `for_trend(hut_id, target_date, days_before)` - Historical trend for specific date

## Management Commands

### update_availability

Fetch and store availability data using `Hut.get_bookings()`.

**Usage:**

```bash
# Update huts needing updates (default - priority-based)
python manage.py update_availability

# Update specific hut
python manage.py update_availability --hut-slug <slug>
python manage.py update_availability --hut-id <id>

# Update all huts with booking references
python manage.py update_availability --all

# Dry run (preview without changes)
python manage.py update_availability --dry-run

# Custom parameters
python manage.py update_availability --days 365 --request-interval 0.1
```

**Options:**

- `--hut-slug <slug>` - Update specific hut by slug
- `--hut-id <id>` - Update specific hut by ID
- `--all` - Force update all huts with booking references
- `--dry-run` - Preview without making changes
- `--days <n>` - Number of days to fetch (default: 365)
- `--request-interval <seconds>` - Time between requests to external API per hut (default: 0.1)
- `--profile` - Enable profiling to identify performance bottlenecks
- `--no-progress` - Disable progress bar and print results line-by-line (useful for cron jobs)

**Default Behavior (no arguments):**

When run without arguments, the command intelligently selects huts to update based on:

1. **Priority-based selection** - Huts already in the availability table that need updates based on occupancy and last check time:
   - High priority (30 min): Full/nearly-full dates (>75% occupancy) in next 14 days
   - Medium priority (3 hours): Moderate occupancy (25-75%) in next 14 days  
   - Low priority (24 hours): Low occupancy (≤25%) in next 14 days

2. **New huts** - Huts with `booking_ref` set but not yet in the availability table

This ensures both regular updates of existing data and discovery of new huts.

**Process:**

The command uses **batched fetching** to reduce memory usage and improve fault tolerance:

1. **Batch 1**: Fetch 30 huts from external API → Save to database
2. **Batch 2**: Fetch next 30 huts → Save to database
3. Continue until all huts are processed

For each hut:
1. Fetches booking data from external API with `cached=False` (real-time data)
2. Extracts all fields from `HutBookingSchema`
3. Creates or updates `HutAvailability` records
4. Records changes to `HutAvailabilityHistory` with timestamps
5. Updates `last_checked` on unchanged records

**Batch Processing Benefits:**
- Lower memory usage (only hold one batch at a time)
- Better fault tolerance (partial progress saved if later batches fail)
- Reduced load on external servers (requests spread over time)
- Faster time-to-first-result (start saving data after first batch)

**Progress Display:**
- **With progress bar** (default): Shows real-time progress with batch info
  ```
  ✓ Fetching from external API... ████████░░ 30/153 • 00:15 Batch 1/6
  ✓ Saving to database...        ████████░░ 30/153 • 00:03 Batch 1/6
  ```
- **With `--no-progress`**: Prints each hut as it's processed (useful for cron jobs)
  ```
  [1/153] Batch 1/6 - Fetching Cabane de Susanfe CAS (susanfe)...
  [1/153] Batch 1/6 - Saving Cabane de Susanfe CAS (susanfe)...
  [2/153] Batch 1/6 - Fetching Capanna Campo Tencia CAS (campo-tencia)...
  ...
  ```

## Data Flow

### On First Fetch

1. Create `HutAvailability` record with all fields
2. Create initial `HutAvailabilityHistory` entry

### On Subsequent Fetches

- **If data changed:**
  1. Update `last_checked` on previous history entry
  2. Create new history entry with `first_checked` = now
  3. Update current `HutAvailability` record

- **If data unchanged:**
  1. Update `last_checked` on current history entry
  2. Auto-update `last_checked` on `HutAvailability` (via auto_now)

## Schema Alignment

The models are aligned with `HutBookingSchema` from hut-services:

```python
# HutBookingSchema fields → Model fields
booking.free → free
booking.total → total
booking.occupancy_percent → occupancy_percent
booking.occupancy_steps → occupancy_steps
booking.occupancy_status → occupancy_status (enum value as string)
booking.reservation_status → reservation_status (enum value as string)
booking.link → link
booking.date → availability_date
booking.hut_type → hut_type
```

All computed fields (occupancy_percent, occupancy_steps, occupancy_status) are stored directly for fast retrieval, rather than computed on-the-fly.

## Django Admin

The app includes a comprehensive admin interface with:

### HutAvailabilityAdmin

- View all current availability records
- Filter by occupancy status, reservation status, hut type, organization, and date
- Search by hut name or slug
- Inline display of history records
- Read-only fields (data managed via management command)
- Custom displays for places (free/total) and occupancy percentage

### HutAvailabilityHistoryAdmin

- View all historical changes
- Filter by occupancy status, hut type, and date
- See duration of each state (auto-calculated)
- Read-only (append-only table)

Both admins are read-only to prevent manual data corruption - all data is managed via the `update_availability` command.

## Scheduled Updates

Set up a Kubernetes CronJob to run updates every 30 minutes:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hut-availability-update
spec:
  schedule: "*/30 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: django-manage
            image: your-django-image
            command: ["python", "manage.py", "update_availability"]
```

## Performance Optimizations

The availability service has been extensively optimized for high-performance bulk updates:

### Database Optimizations

**1. Batched External Fetching & Database Processing**

- Fetches and processes huts in batches of 30 (default: `batch_size=30`)
- Each batch: Fetch from API → Save to DB → Move to next batch
- Sequential processing prevents memory issues and reduces external server load
- Configurable via `batch_size` parameter in service

**2. Bulk Operations**

- Uses Django's `bulk_create()` and `bulk_update()` for all database writes
- Single query creates/updates hundreds of records instead of N individual queries
- Significantly faster than individual `.save()` calls

**3. Query Optimization**

- Uses `select_related('hut', 'source_organization', 'hut_type')` to eliminate N+1 queries
- Pre-fetches all foreign key relationships in single query
- Critical performance improvement: reduces 50k+ queries to 1 query per batch

**4. Efficient History Updates**

- Updates `history.last_checked` using optimized raw SQL with PostgreSQL's `DISTINCT ON`
- Single query updates thousands of history records efficiently
- Custom SQL necessary as Django ORM doesn't support `DISTINCT ON` efficiently

**5. Minimal Locking**

- No row-level locks during updates for better concurrency
- Atomic transactions provide sufficient consistency
- Each batch processed in a single transaction

### External API Optimizations

- **Batched fetching** - Fetches 30 huts per batch from external API with `cached=False`
- **Real-time data** - Disables cache to ensure batched fetching works correctly
- **Rate limiting** - `request_interval` controls spacing between individual hut requests (default: 0.1s)
- **Progress tracking** - Real-time progress bar using `rich` library shows fetch and DB progress with batch info

### Performance Metrics

**Typical performance for 150 huts with 365 days each (~55k records):**

- External API fetch: ~75-80 seconds (limited by rate limiting)
- Database processing: ~95-100 seconds
  - Bulk updates: ~50 seconds
  - History updates: ~45 seconds
- **Total: ~180 seconds** (~1.2 seconds per hut)

**Profiling:**
Use `--profile` flag to identify performance bottlenecks:

```bash
python manage.py update_availability --all --profile
```

### Current Architecture

```python
# Batched fetch and process with optimized database operations
batch_result = AvailabilityService.update_huts_availability(
    huts=huts_list,
    days=365,
    request_interval=0.1,
    batch_size=30,  # Huts per batch (fetch + DB transaction)
    update_history_last_checked=True,  # Enable duration tracking
    fetch_progress_callback=fetch_callback,
    process_progress_callback=process_callback,
)
```

The service automatically:

1. **Splits huts into batches of 30**
2. **For each batch:**
   - Fetches booking data from external API (with `cached=False` for real-time data)
   - Processes and saves all data in a single optimized database transaction
   - Updates availability and history records efficiently
3. **Moves to next batch** - Sequential processing ensures low memory usage and fault tolerance

## API Endpoints

The app provides RESTful API endpoints for querying availability data:

### GeoJSON Map View

**Endpoint:** `GET /v1/huts/availability/{date}.geojson`

Returns availability data as GeoJSON FeatureCollection for map visualization.

**Path Parameters:**
- `date` - ISO date (2026-01-15), 'now', 'today', or 'weekend'

**Query Parameters:**
- `slugs` - Comma-separated list of hut slugs to filter (optional)
- `days` - Number of days from start date (default: 1)
- `offset` - Pagination offset (default: 0)
- `limit` - Pagination limit (optional)

**Examples:**
```bash
GET /v1/huts/availability/now.geojson
GET /v1/huts/availability/today.geojson?days=7&limit=10
GET /v1/huts/availability/2026-01-15.geojson?slugs=aarbiwak,almageller
GET /v1/huts/availability/weekend.geojson
```

**Response Schema:** `HutAvailabilityFeatureCollection`

### Current Availability (Single Hut)

**Endpoint:** `GET /v1/huts/{slug}/availability/{date}`

Returns detailed current availability data for a specific hut with metadata.

**Path Parameters:**
- `slug` - Hut slug identifier
- `date` - ISO date (2026-01-15), 'now', 'today', or 'weekend'

**Query Parameters:**
- `days` - Number of days from start date (default: 1)

**Examples:**
```bash
GET /v1/huts/aarbiwak/availability/now
GET /v1/huts/aarbiwak/availability/2026-01-15?days=7
GET /v1/huts/aarbiwak/availability/weekend?days=3
```

**Response Schema:** `CurrentAvailabilitySchema`

**Includes:**
- Hut metadata (slug, id, source_id, source)
- `source_link` - External link to hut page on source organization's website
- Availability data with:
  - `link` - Booking link for each specific date
  - `first_checked` - When availability was first recorded
  - `last_checked` - When availability was last checked
  - All occupancy and reservation data

**Use Case:** Display detailed availability with booking links and freshness indicators.

### Availability Trend/History

**Endpoint:** `GET /v1/huts/{slug}/availability/{date}/trend`

Returns historical availability changes for a specific hut and date.

**Path Parameters:**
- `slug` - Hut slug identifier
- `date` - Target date - ISO date (2026-01-15), 'now', 'today', or 'weekend'

**Query Parameters:**
- `limit` - How many days back to show history (default: 7)

**Examples:**
```bash
GET /v1/huts/aarbiwak/availability/2026-01-15/trend?limit=30
GET /v1/huts/aarbiwak/availability/weekend/trend
```

**Response Schema:** `AvailabilityTrendSchema`

**Includes:**
- Historical changes ordered by `first_checked` (newest first)
- For each change:
  - `first_checked` - When this state was first observed
  - `last_checked` - When this state was last confirmed
  - `duration_seconds` - How long this state lasted
  - All occupancy and reservation data

**Use Case:** Show how availability for a future date evolved over time as people made/cancelled bookings.

### API Features

- **RESTful design** - Date as resource identifier in path
- **Caching** - HTTP cache headers (10 min for map, 5 min for single hut)
- **Validation** - Full Pydantic schema validation
- **OpenAPI** - Auto-generated documentation at `/v1/openapi.json`
- **Language support** - `lang` parameter (de, en, fr, it)

### Date Format Support

All endpoints accept these date formats:
- **Special keywords:** `now`, `today`, `weekend`
- **ISO dates:** `2026-01-15`, `26-01-15`
- **European format:** `15.01.2026`, `15.01.26`
- **Slash format:** `2026/01/15`, `26/01/15`

### Deprecated Endpoints

The following endpoints are deprecated and will be removed in a future version:

- `GET /v1/huts/bookings` → Use `/v1/huts/availability/{date}.geojson`
- `GET /v1/huts/bookings.geojson` → Use `/v1/huts/availability/{date}.geojson`

## Future Enhancements

### Generator-based External Fetching

**Current limitation:** All huts are fetched and returned as a complete list before processing begins. For very large batches, this can cause memory issues and delays the start of database updates.

**Proposed improvement:** Refactor `hut-services-private` to use a generator pattern:

```python
# Future: Generator yields results as they're fetched
for hut_result in service.get_bookings_generator(
    hut_slugs=slugs,
    request_interval=0.1
):
    # Process and store each hut immediately
    process_hut_bookings(hut_result)
    progress_callback()
```

**Benefits:**

- **Streaming processing** - Start storing data while still fetching remaining huts
- **Lower memory usage** - Don't hold all results in memory at once
- **Better progress granularity** - Progress updates happen as each hut is fetched
- **Request interval stays in external service** - Rate limiting remains where it belongs

**Implementation notes:**

- Modify `hut-services-private` to yield `HutBookingsSchema` objects one at a time
- Rate limiting (`request_interval`) stays in the external service between yields
- Progress callback gets called after each yield in the availability service
- Maintains clean separation of concerns (external fetching vs. database storage)

### Other Enhancements

- Add API endpoints (Django Ninja) for querying availability
- Add trend analysis endpoints
- Implement async task queue (Celery) for large batch updates
- Add parallel service calls when multiple external services are available
- Add data retention policies for old history entries
