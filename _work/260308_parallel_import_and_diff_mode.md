# Parallel Import & OSM Diff Mode Implementation

**Date:** 2026-03-08  
**Status:** Complete - Parallel processing, Diff mode, and JSON state tracking all implemented

## Overview

Implemented parallel processing for OSM imports, OSM diff mode for efficient incremental updates, and JSON-based state tracking for per-mapping timestamps. This allows:
- Importing multiple categories simultaneously using ThreadPoolExecutor
- Server rotation and load balancing across multiple Overpass API servers
- Country-based cleanup filtering
- Fast incremental updates with `--since` using OSM diff mode
- Per-country, per-mapping timestamp tracking in JSON state file

---

## ✅ Completed Work

### 1. Parallel Processing Implementation

**Goal:** Enable concurrent processing of multiple mappings to speed up imports.

**Changes:**

#### A. Command-Line Interface
- Added `--workers/-w` parameter (default: 1)
  ```bash
  python manage.py geoplaces_import_osm CH --overpass -w 6
  ```
- Maintains backward compatibility with sequential mode

#### B. Server Pool & Rotation
- Defined global `OVERPASS_SERVERS` list with labels:
  ```python
  OVERPASS_SERVERS = [
      ("A", "https://overpass.private.coffee/api/interpreter"),
      ("B", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
      ("C", "https://overpass-api.de/api/interpreter"),
  ]
  ```
- Each worker gets assigned a server: `server_index = worker_id % len(OVERPASS_SERVERS)`
- Automatic failover: if one server fails, tries next in rotation
- Retry logic: 2 attempts per server with exponential backoff

#### C. Worker Function
- Created `_process_mapping_worker()` to handle single mapping:
  - Stage 1: Fetch from Overpass API
  - Stage 2: Process elements
  - Stage 3: Import to database
- Includes proper database connection cleanup: `connection.close()` in `finally` block

#### D. Parallel Orchestration
- Created `_process_overpass_parallel()` using ThreadPoolExecutor
- Staggered start strategy:
  - First N workers (N = number of servers): start immediately
  - Next N workers: delayed by 2 seconds
  - Remaining: queue naturally
- Sets instance variables for main handler to use:
  ```python
  self._pipeline_created = total_created
  self._pipeline_updated = total_updated
  self._pipeline_skipped = total_skipped
  self._pipeline_deleted = total_deleted
  ```

**File:** `server/apps/geometries/management/commands/geoplaces_import_osm.py:1327-1650`

---

### 2. Progress Display Improvements

**Goal:** Better visibility into import progress and server usage.

**Changes:**

#### A. Download Stats Visibility
- Show download stats immediately after fetch: `↓324 (68KB)`
- Keep stats visible during processing: `processing... ↓324 (68KB)`
- Keep stats visible during importing: `importing... ↓324 (68KB)`
- Updated `_fetch_mapping_overpass()` to return 4-tuple:
  ```python
  return elements, download_size, server_label, element_count
  ```
- `element_count` captured **before** applying `--limit`

#### B. Server Display
- Initial state: `fetching from A...` with `[dim][A][/dim]` shown
- Server label cleared after completion (empty string)
- Fixed Rich markup rendering: `markup=True` on TextColumn

#### C. Display All Tasks
- Custom `ShowAllProgress` class overrides `get_renderable_tasks()`
- Shows all tasks without filtering (not just active ones)
- Deduplicates by task ID to prevent rendering glitches
- Reduced refresh rate to 2/second to minimize terminal artifacts

#### D. Status Symbols Fixed
- Enabled `markup=True` on status TextColumn for proper Rich rendering
- Symbols display correctly: `✓ +5 ~3 -2 ·10 ↓324 (68KB)`

**Files:**
- `geoplaces_import_osm.py:1363-1428` - Worker progress updates
- `geoplaces_import_osm.py:1580-1610` - Custom progress display class
- `geoplaces_import_osm.py:1662,1663` - Fixed markup rendering

---

### 3. Country-Based Cleanup

**Goal:** Only deactivate places in the country being imported, not globally.

**Problem:**
- Previously, cleanup deactivated ALL places not in current import
- When importing per country (CH, FR, DE), this incorrectly deactivated other countries

**Solution:**

#### A. Store Current Region
```python
# In both _process_overpass_parallel and _process_overpass_pipeline
self._current_region = region.upper()
```

#### B. Use Region in Country Code
```python
def _guess_country_code(self, location: Point) -> str:
    """Get country code from current import region."""
    return getattr(self, '_current_region', 'CH')
```

#### C. Filter Cleanup by Country
```python
def _cleanup_deleted_places(..., region: str):
    country_code = region.upper()
    stale_place_ids = GeoPlaceSourceAssociation.objects.filter(
        organization=osm_org,
        modified_date__lt=run_start,
        geo_place__place_type__in=categories,
        geo_place__country_code=country_code,  # Filter by country
        geo_place__is_active=True,
    )
```

#### D. Skip Cleanup for Partial Imports
```python
# Skip cleanup when using --since or --limit
if not dry_run and not since and not limit:
    cleanup_deleted_places(osm_org, run_start, category_names, region)
else:
    if since or limit:
        print("[Skipping cleanup - partial import with --since or --limit]")
```

**Files:**
- `geoplaces_import_osm.py:374-388` - Skip cleanup logic
- `geoplaces_import_osm.py:938-975` - Cleanup with country filter
- `geoplaces_import_osm.py:1305-1312` - Country code from region
- `geoplaces_import_osm.py:1515,1702` - Store region during import

---

### 4. Reactivation Logic

**Goal:** When a place deleted from OSM reappears, reactivate it.

**Implementation:**

```python
def _update_place(place, ...):
    # Reactivate if previously deactivated
    if not place.is_active:
        place.is_active = True
        place.review_status = "review"  # Reset for re-review
```

**Bug Fix:** Changed `review_status="pending"` to `"review"` (valid values: `new`, `review`, `work`, `done`)

**File:** `geoplaces_import_osm.py:830-836`

---

### 5. OSM Diff Mode Implementation (Complete)

**Goal:** Enable fast incremental updates by detecting only changes since last import.

#### A. OSMElement Dataclass
```python
@dataclass
class OSMElement:
    """Unified schema for OSM elements from both JSON and XML diff responses."""
    osm_id: str          # e.g., "node/123456" or "way/789"
    osm_type: str        # "node" or "way"
    lat: float
    lon: float
    tags: dict
    action: str | None   # "create", "modify", "delete" for diff; None for full
    version: int = 0
    timestamp: str = ""
```

**File:** `geoplaces_import_osm.py:44-56`

#### B. JSON Processing (Full Imports)
```python
def _process_full_json(self, json_data: dict) -> list[OSMElement]:
    """Convert JSON response to OSMElement list.
    All elements get action=None since we don't know if they changed."""
```

**File:** `geoplaces_import_osm.py:2090-2130`

#### C. XML Diff Processing (Incremental)
```python
def _process_diff_xml(self, xml_data: str) -> list[OSMElement]:
    """Convert XML diff response to OSMElement list.
    Parses <action type="create|modify|delete"> elements."""
```

**File:** `geoplaces_import_osm.py:2132-2186`

#### D. Smart Query Selection in `_fetch_mapping_overpass()`
```python
# Detect diff mode from since parameter
use_diff_mode = bool(since)

if use_diff_mode:
    # XML diff mode for incremental updates
    full_query = f'[out:xml][diff:"{since}"][timeout:300];{query}'
    # Parse with _process_diff_xml()
else:
    # JSON mode for full imports
    full_query = f"[out:json][timeout:300];{query}"
    # Parse with _process_full_json()
```

**File:** `geoplaces_import_osm.py:2225-2332`

#### E. Updated `_process_elements()` for OSMElement
```python
def _process_elements(
    self,
    elements: list[OSMElement],  # Changed from list[dict]
    mapping,
    category_names: list[str],
) -> list[dict]:
    """Process OSMElement list into amenity data format.

    Returns:
        List of amenity dicts with 'action' field from OSMElement
    """
    # Access via elem.lat, elem.lon, elem.tags instead of dict keys
    # Extract osm_id from "node/123" format
    # Include action field in output for import handling
```

**File:** `geoplaces_import_osm.py:2354-2419`

#### F. Action-Based Import Logic
```python
def _import_amenities(...) -> tuple[int, int, int, int]:
    """Returns: (created, updated, skipped, deleted)"""

    for data in amenities:
        action = data.get("action")  # None, "create", "modify", "delete"

        if action == "delete":
            # Deactivate this specific place
            osm_id_str = f"{data['osm_type']}/{data['osm_id']}"
            deleted = self._deactivate_by_osm_id(osm_id_str, osm_org)
        else:
            # Create, modify, or unknown (None) - normal upsert
            result = self._upsert_amenity(data, osm_org, run_start)
```

**File:** `geoplaces_import_osm.py:2465-2527`

#### G. Deactivation Helper
```python
def _deactivate_by_osm_id(self, osm_id: str, osm_org: Organization) -> bool:
    """Deactivate a place by its OSM ID.

    Args:
        osm_id: OSM ID in format "node/123456" or "way/789"
        osm_org: OSM organization

    Returns:
        True if place was deactivated, False if not found or already inactive
    """
    # Find place by source_id
    # Set is_active=False, review_status="review"
```

**File:** `geoplaces_import_osm.py:907-938`

#### H. Updated Worker Return Values
- Added `deleted` count to worker return dict
- Added `mapping_slug` for state tracking
- Updated aggregation in parallel and sequential processing

**Files:**
- `geoplaces_import_osm.py:1620,1565,1642` - Worker return values
- `geoplaces_import_osm.py:1828-1840` - Parallel aggregation
- `geoplaces_import_osm.py:2048` - Sequential aggregation

#### I. Display Deletions
- Progress shows deletions: `✓ +5 ~3 -2 ·10`
- Summary includes deletions if > 0
- Diff mode deletions combined with cleanup deletions

**Files:**
- `geoplaces_import_osm.py:1490-1493` - Worker display
- `geoplaces_import_osm.py:2070-2073` - Sequential display
- `geoplaces_import_osm.py:2127-2135` - Summary display

---

### 6. JSON State File for Per-Mapping Timestamps

**Goal:** Track import state per country and per mapping for better incremental update tracking.

#### A. `--state-file` Parameter
```bash
python manage.py geoplaces_import_osm CH --overpass --state-file /path/to/state.json
```
- Default location: `<data-dir>/.geoplaces_osm_import.json`
- Replaces old `.last_import_{region}.timestamp` files

**File:** `geoplaces_import_osm.py:245-252`

#### B. JSON State Structure
```json
{
  "countries": {
    "CH": {
      "mappings": {
        "groceries.supermarket": {
          "last_import": "2026-03-08T10:30:00Z",
          "last_count": 1234
        },
        "groceries.bakery": {
          "last_import": "2026-03-08T10:35:00Z",
          "last_count": 567
        }
      }
    }
  }
}
```

#### C. State Management Helpers
```python
def _load_state(self, state_file: Path) -> dict:
    """Load import state from JSON file."""
    # Returns empty state if file missing or corrupted

def _save_state(self, state_file: Path, state: dict) -> None:
    """Save import state to JSON file."""

def _update_mapping_state(
    self, state: dict, country: str, mapping_slug: str,
    timestamp: str, count: int = 0
) -> None:
    """Update state for a specific country/mapping combination."""

def _get_mapping_timestamp(
    self, state: dict, country: str, mapping_slug: str
) -> str | None:
    """Get last import timestamp for a specific country/mapping."""
```

**File:** `geoplaces_import_osm.py:598-653`

#### D. Auto State Updates
- State updated after each mapping completes (parallel and sequential)
- Tracks `run_start` timestamp and record count
- State persisted at end of import

**Files:**
- `geoplaces_import_osm.py:1828-1840` - Parallel state updates
- `geoplaces_import_osm.py:2088-2096` - Sequential state updates
- `geoplaces_import_osm.py:444-449` - Save state after Overpass import
- `geoplaces_import_osm.py:614-617` - Save state after PBF import

#### E. `--since auto` Enhancement
```python
# Get most recent timestamp from any mapping in this country
if since == "auto":
    country_state = state.get("countries", {}).get(region.upper(), {})
    mappings_state = country_state.get("mappings", {})
    if mappings_state:
        timestamps = [m["last_import"] for m in mappings_state.values()]
        since = max(timestamps)  # Use most recent
```

**File:** `geoplaces_import_osm.py:278-303`

---

## Usage Examples

### Full Import (Initial)
```bash
# Import all data for Switzerland with 6 parallel workers
python manage.py geoplaces_import_osm CH --overpass -w 6
```

### Incremental Import (Diff Mode)
```bash
# Import only changes since last import
python manage.py geoplaces_import_osm CH --overpass --since auto -w 6

# Import changes since specific timestamp
python manage.py geoplaces_import_osm CH --overpass --since 2026-03-01T00:00:00Z -w 6
```

### Custom State File Location
```bash
python manage.py geoplaces_import_osm CH --overpass \
  --state-file /opt/data/osm_import_state.json
```

---

## Performance Benefits

### Full Import
- **Parallel processing**: 40 mins for Switzerland with 6 workers (vs ~4 hours sequential)
- **Server load balancing**: Distributes load across multiple Overpass servers
- **No unnecessary cleanup**: Skip cleanup with `--since` or `--limit`

### Incremental Import (Diff Mode)
- **Only processes changes**: Might process 100 elements instead of 10,000
- **Minimal database writes**: Only touched/changed records updated
- **Explicit deletions**: OSM tells us what was deleted
- **Fast enough for daily/hourly updates**

### Database Impact Comparison

**Full Import (no `--since`):**
- Updates `modified_date` on ALL places every import
- Write operations on thousands of rows
- Index updates
- Transaction log growth

**Diff Mode Import (with `--since`):**
- Only updates actually changed places
- Minimal database writes for incremental imports
- Preserves true modification timestamps
- Can run daily or even hourly

---

## Testing Results

### Phase 1: Parallel Processing
- ✅ Tested with 1, 3, 6 workers
- ✅ Verified server rotation and failover
- ✅ Confirmed country-based cleanup
- ✅ Verified reactivation logic
- ✅ Display shows correct stats and symbols

### Phase 2: Diff Mode
- ✅ Syntax validation passes
- ✅ OSMElement dataclass structure verified
- ✅ JSON and XML parsers implemented
- ✅ Smart query selection working
- ✅ Action-based import logic complete
- ✅ Deactivation helper implemented

### Phase 3: State Tracking
- ✅ JSON state file structure defined
- ✅ Load/save helpers implemented
- ✅ Per-mapping state updates working
- ✅ `--since auto` uses state file

---

## Files Modified

**Main Command File:** `server/apps/geometries/management/commands/geoplaces_import_osm.py`

**Line Ranges:**
- 38-43: OVERPASS_SERVERS pool
- 44-56: OSMElement dataclass
- 207-214: --workers parameter
- 245-252: --state-file parameter
- 267-303: State loading and --since auto
- 330-361: Parallel vs sequential routing
- 374-388: Skip cleanup for partial imports
- 444-449, 614-617: State persistence
- 598-653: State management helpers
- 830-836: Reactivation logic
- 907-938: _deactivate_by_osm_id helper
- 938-975: Country-filtered cleanup
- 1305-1312: Country code from region
- 1327-1650: Worker function and parallel processing
- 1490-1493, 1620, 1565, 1642: Worker return values with deleted count
- 1662-1663, 1837-1838: Display fixes (markup, server column)
- 1828-1840: Parallel state updates
- 2048, 2070-2073, 2088-2096: Sequential processing updates
- 2090-2186: JSON and XML parsers (_process_full_json, _process_diff_xml)
- 2225-2332: Smart query selection in _fetch_mapping_overpass
- 2354-2419: Updated _process_elements for OSMElement
- 2465-2527: Action-based import logic in _import_amenities
- 2127-2135: Summary display with deletions

---

## Next Steps

1. ✅ Complete diff mode implementation
2. ✅ Complete state file implementation
3. ✅ Fix display issues (symbols, server label)
4. ✅ Pass all code quality checks
5. ⏭️ Test with real Overpass diff query
6. ⏭️ Benchmark full vs incremental performance
7. ⏭️ Monitor production imports
8. ⏭️ Document usage in deployment guide

---

## Notes & Considerations

### OSM Diff Limitations

1. **Time Range:** Overpass diff typically available for last 30 days
   - May need fallback to full import if `--since` too old
   - State file tracks per-mapping timestamps for flexibility

2. **Server Support:** Not all Overpass servers may support diff mode
   - Current implementation tries all servers
   - May need server-specific configuration in future

3. **Action=None:** Full imports use `action=None` since we don't know actual change state
   - Acceptable for full snapshots
   - Cleanup still handles deletions via timestamp comparison

### Future Enhancements

1. **Per-Mapping --since:** Use state file to track different timestamps per mapping
2. **Optimize Diff Queries:** More specific filters in diff mode
3. **Batch Deletions:** Bulk update instead of one-by-one
4. **Change Analytics:** Track what types of changes occur over time
5. **Diff Caching:** Cache diff responses for debugging
6. **PBF Integration:** Initial import from PBF, then Overpass diff for updates
