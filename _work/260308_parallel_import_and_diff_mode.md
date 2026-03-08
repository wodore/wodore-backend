# Parallel Import & OSM Diff Mode Implementation

**Date:** 2026-03-08  
**Status:** Partial - Parallel processing complete, Diff mode foundation in place

## Overview

Implemented parallel processing for OSM imports and laid groundwork for efficient incremental updates using OSM diff mode. This allows:
- Importing multiple categories simultaneously using ThreadPoolExecutor
- Server rotation and load balancing across multiple Overpass API servers
- Country-based cleanup filtering
- Foundation for fast incremental updates with `--since`

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
  ```

**File:** `server/apps/geometries/management/commands/geoplaces_import_osm.py:1327-1620`

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
- Initial state: `fetching from A...`
- Shows server label throughout: `[A]`, `[B]`, `[C]`
- Header displays server pool:
  ```
  Server Pool:
    [A] overpass.private.coffee
    [B] maps.mail.ru
    [C] overpass-api.de
  ```

#### C. Display All Tasks
- Custom `ShowAllProgress` class overrides `get_renderable_tasks()`
- Shows all tasks without filtering (not just active ones)
- Deduplicates by task ID to prevent rendering glitches
- Reduced refresh rate to 2/second to minimize terminal artifacts

**Files:**
- `geoplaces_import_osm.py:1363-1428` - Worker progress updates
- `geoplaces_import_osm.py:1580-1610` - Custom progress display class

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
        geo_place__country_code=country_code,  # NEW: filter by country
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
- `geoplaces_import_osm.py:893-930` - Cleanup with country filter
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

### 5. OSM Diff Mode Foundation

**Goal:** Enable fast incremental updates by detecting only changes since last import.

**Completed:**

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
    action: str          # "create", "modify", "delete", "nochange"
    version: int = 0
    timestamp: str = ""
```

#### B. JSON Processing (Full Imports)
```python
def _process_full_json(self, json_data: dict) -> list[OSMElement]:
    """Convert JSON response to OSMElement list.

    All elements get action='nochange' since it's a full snapshot.
    """
    # Parses Overpass JSON response
    # Returns list of OSMElement with action='nochange'
```

#### C. XML Diff Processing (Incremental)
```python
def _process_diff_xml(self, xml_data: str) -> list[OSMElement]:
    """Convert XML diff response to OSMElement list.

    Parses <action type="create|modify|delete"> elements.
    """
    # Parses Overpass XML diff response
    # Returns list of OSMElement with action from diff
```

**Files:**
- `geoplaces_import_osm.py:44-56` - OSMElement dataclass
- `geoplaces_import_osm.py:1934-1973` - JSON processing
- `geoplaces_import_osm.py:1975-2030` - XML diff processing

---

## 🔨 Remaining Work for Diff Mode

### 1. Update `_fetch_mapping_overpass()`

**Current:** Always uses JSON mode with `(newer:"{since}")` filter

**Needed:**
- Choose output format based on `since` parameter:
  ```python
  if since:
      # Use XML diff mode
      query_prefix = f'[out:xml][diff:"{since}"][timeout:300];'
      response_type = 'xml'
  else:
      # Use JSON mode
      query_prefix = '[out:json][timeout:300];'
      response_type = 'json'
  ```

- Parse response based on type:
  ```python
  if response_type == 'json':
      elements = self._process_full_json(response.json())
  else:  # xml
      elements = self._process_diff_xml(response.text)
  ```

- Return `List[OSMElement]` instead of raw dict elements

**File:** `geoplaces_import_osm.py:2038-2145`

---

### 2. Update `_process_elements()`

**Current signature:**
```python
def _process_elements(
    self,
    elements: list[dict],  # Raw Overpass dicts
    mapping,
    category_names: list[str],
) -> list[dict]:
```

**Needed signature:**
```python
def _process_elements(
    self,
    elements: list[OSMElement],  # Structured elements
    mapping,
    category_names: list[str],
) -> list[dict]:  # Still returns amenity dicts
```

**Changes:**
- Access fields via dataclass attributes instead of dict keys
- Use `elem.tags` instead of `elem.get('tags', {})`
- Add OSM ID to output: `osm_id=elem.osm_id, osm_type=elem.osm_type`

**File:** `geoplaces_import_osm.py:2092-2180`

---

### 3. Update Import Logic

**Current:** `_import_amenities()` processes all elements the same way

**Needed:** Handle `action` field differently:

```python
def _import_elements(self, elements: list[OSMElement], ...):
    """Import elements based on their action type."""

    created = updated = skipped = deleted = 0

    for elem in elements:
        if elem.action == 'delete':
            # Deactivate this specific place
            deleted += self._deactivate_by_osm_id(elem.osm_id)

        elif elem.action in ['create', 'modify']:
            # Create or update place
            amenity_data = self._osm_element_to_amenity(elem, mapping)
            result = self._upsert_amenity(amenity_data, osm_org, run_start)
            if result == 'created':
                created += 1
            elif result == 'updated':
                updated += 1

        elif elem.action == 'nochange':
            # Full import - current behavior
            amenity_data = self._osm_element_to_amenity(elem, mapping)
            result = self._upsert_amenity(amenity_data, osm_org, run_start)
            # ... track stats

    return created, updated, skipped, deleted
```

**Helper needed:**
```python
def _osm_element_to_amenity(self, elem: OSMElement, mapping) -> dict:
    """Convert OSMElement to amenity dict format."""
    return {
        'osm_id': elem.osm_id.split('/')[1],  # Extract numeric ID
        'osm_type': elem.osm_type,
        'lat': elem.lat,
        'lon': elem.lon,
        'tags': elem.tags,
        'name': elem.tags.get('name'),
        'category_slug': mapping.category_slug,
        # ... other fields from tags
    }
```

---

### 4. Add `_deactivate_by_osm_id()` Helper

```python
def _deactivate_by_osm_id(self, osm_id: str) -> int:
    """Deactivate a place by its OSM ID.

    Args:
        osm_id: Format "node/123456" or "way/789"

    Returns:
        1 if deactivated, 0 if not found
    """
    from server.apps.geometries.models import GeoPlaceSourceAssociation

    # Extract numeric ID from "node/123" format
    source_id = osm_id.split('/')[1]

    try:
        assoc = GeoPlaceSourceAssociation.objects.get(
            organization__slug='osm',
            source_id=source_id
        )

        if assoc.geo_place.is_active:
            assoc.geo_place.is_active = False
            assoc.geo_place.review_status = 'review'
            assoc.geo_place.save()
            return 1

    except GeoPlaceSourceAssociation.DoesNotExist:
        pass

    return 0
```

---

### 5. Update Worker to Track Deletions

**Current return:**
```python
return {
    "created": created,
    "updated": updated,
    "skipped": skipped,
    "download_bytes": download_size,
    "server_label": server_label,
    "success": True,
}
```

**Needed:**
```python
return {
    "created": created,
    "updated": updated,
    "skipped": skipped,
    "deleted": deleted,  # NEW
    "download_bytes": download_size,
    "server_label": server_label,
    "success": True,
}
```

Update aggregation in `_process_overpass_parallel()`:
```python
total_deleted = 0
# ...
for future in as_completed(futures):
    result = future.result()
    total_created += result["created"]
    total_updated += result["updated"]
    total_skipped += result["skipped"]
    total_deleted += result.get("deleted", 0)  # NEW
```

---

## Expected Benefits After Completion

### Performance Improvements

**Full Import (no `--since`):**
- ✅ Already faster with parallel processing
- Current: ~40 mins for Switzerland with 6 workers
- Unchanged by diff mode (still uses JSON)

**Incremental Import (with `--since`):**
- 🚀 **Much faster** - only processes actual changes
- Only touches changed/created/deleted places in database
- No timestamp updates for unchanged records
- Example: Daily update might process 100 changes instead of 10,000 records

### Database Impact

**Current (Full Import):**
- Updates `modified_date` on ALL places every import
- Write operations on thousands of rows
- Index updates
- Transaction log growth

**After Diff Mode:**
- Only updates actually changed places
- Minimal database writes for incremental imports
- Preserves true modification timestamps
- Can run daily or even hourly

### Use Cases

1. **Initial Import:** Use full mode (no `--since`)
   ```bash
   python manage.py geoplaces_import_osm CH --overpass -w 6
   ```

2. **Daily Updates:** Use diff mode
   ```bash
   python manage.py geoplaces_import_osm CH --overpass --since auto -w 6
   ```

3. **Weekly Updates:** Use diff mode
   ```bash
   python manage.py geoplaces_import_osm CH --overpass --since 2026-03-01T00:00:00Z -w 6
   ```

---

## Testing Strategy

### Phase 1: Full Import (Already Working)
- [x] Test parallel import with multiple workers
- [x] Verify server rotation and failover
- [x] Check country-based cleanup
- [x] Verify reactivation logic

### Phase 2: Diff Mode (To Do)
- [ ] Test `_process_full_json()` with sample Overpass JSON
- [ ] Test `_process_diff_xml()` with sample Overpass XML diff
- [ ] Test diff query returns expected format
- [ ] Verify deletions are properly handled
- [ ] Test incremental import doesn't touch unchanged records
- [ ] Compare database writes: full vs incremental

### Phase 3: Integration
- [ ] Run full import, then incremental after changes
- [ ] Verify timestamps only update for changed places
- [ ] Test with various time ranges (1 day, 1 week, 1 month)
- [ ] Performance benchmarks

---

## Notes & Considerations

### OSM Diff Limitations

1. **Time Range:** Overpass diff typically available for last 30 days
   - Fallback to full import if `--since` is too old
   - Or show error message

2. **Server Support:** Not all Overpass servers may support diff mode
   - May need to restrict to specific servers
   - Add configuration option to disable diff

3. **Metadata Changes:** Diff may include elements where only version/timestamp changed
   - Acceptable overhead
   - Still much better than full import

### Current Behavior to Preserve

- `--limit` for testing: Still works with both modes
- `--dry-run`: Should work with both modes
- Query file generation: Should output appropriate query type
- Error handling and retry logic
- Progress display and statistics

### Future Enhancements

1. **Optimize Diff Queries:** Use more specific filters in diff mode
2. **Batch Deletions:** Bulk update instead of one-by-one
3. **Change Analytics:** Track what types of changes occur
4. **Diff Caching:** Cache diff responses for debugging
5. **PBF Integration:** Initial import from PBF, then Overpass diff for updates

---

## Files Modified

- `server/apps/geometries/management/commands/geoplaces_import_osm.py` (main changes)
  - Lines 44-56: OSMElement dataclass
  - Lines 207-214: --workers parameter
  - Lines 330-361: Parallel vs sequential routing
  - Lines 374-388: Skip cleanup for partial imports
  - Lines 830-836: Reactivation logic
  - Lines 893-930: Country-filtered cleanup
  - Lines 1305-1312: Country code from region
  - Lines 1327-1453: Worker function
  - Lines 1455-1620: Parallel processing
  - Lines 1934-2030: JSON and XML processing helpers

---

## Related Issues

- Import performance for incremental updates
- Database write overhead during daily syncs
- Multi-country import isolation
- Deleted place detection

---

## Next Steps

1. Complete diff mode implementation (remaining work above)
2. Test with small dataset
3. Benchmark performance difference
4. Deploy to staging
5. Monitor production imports
6. Document usage in deployment guide
