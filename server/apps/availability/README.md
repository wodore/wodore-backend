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
- `--request-interval <seconds>` - Time between requests (default: 0.1)
- `--profile` - Enable profiling to identify performance bottlenecks

**Default Behavior (no arguments):**

When run without arguments, the command intelligently selects huts to update based on:

1. **Priority-based selection** - Huts already in the availability table that need updates based on occupancy and last check time:
   - High priority (30 min): Full/nearly-full dates (>75% occupancy) in next 14 days
   - Medium priority (3 hours): Moderate occupancy (25-75%) in next 14 days  
   - Low priority (24 hours): Low occupancy (≤25%) in next 14 days

2. **New huts** - Huts with `booking_ref` set but not yet in the availability table

This ensures both regular updates of existing data and discovery of new huts.

**Process:**

1. Fetches booking data using `Hut.get_bookings()`
2. Extracts all fields from `HutBookingSchema`
3. Creates or updates `HutAvailability` records
4. Records changes to `HutAvailabilityHistory` with timestamps
5. Updates `last_checked` on unchanged records

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

**1. Batch Processing**

- Processes multiple huts in a single database transaction (default: 20 huts per batch)
- Reduces transaction overhead and improves throughput
- Configurable via `batch_size` parameter

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
- Allows parallel processing if needed in future

### External API Optimizations

- **Single API call** - All huts fetched in one external service call
- **Rate limiting** - `request_interval` controls spacing between individual hut requests
- **Progress tracking** - Real-time progress bar using `rich` library shows fetch and DB progress

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
# Batch fetch and process with optimized database operations
batch_result = AvailabilityService.update_huts_availability(
    huts=huts_list,
    days=365,
    request_interval=0.1,
    batch_size=20,  # Huts per transaction
    update_history_last_checked=True,  # Enable duration tracking
    fetch_progress_callback=fetch_callback,
    process_progress_callback=process_callback,
)
```

The service automatically:

1. Fetches all huts from external API
2. Groups huts into batches of 20
3. Processes each batch in optimized transaction
4. Updates availability and history records efficiently

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
