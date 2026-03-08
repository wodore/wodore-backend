# OSM Food Supply Import Implementation

**Date**: 2026-03-07  
**Status**: Initial Implementation Complete  
**Command**: `app geoplaces_import_osm`

---

## Overview

Implemented a Django management command to import food supply amenities (supermarkets, bakeries, grocery stores, etc.) from OpenStreetMap via Geofabrik PBF files.

---

## Changes Made

### 1. Dependencies Added

**File**: `pyproject.toml`

Added the following dependencies:

```toml
"osmium>=3.7.0",  # Python bindings for OSM data parsing
"httpx>=0.27.0",  # Modern HTTP client for downloads
"opening-hours-py>=1.1.6",  # OSM opening_hours format parser (Rust-based)
```

### 2. AmenityDetail Model Update

**File**: `server/apps/geometries/models/_amenity_detail.py`

**Removed**: `websites` field (now handled via ExternalLinks M2M)

**Kept**: `phones` field as JSONField for simple phone number storage

### 3. Management Command

**File**: `server/apps/geometries/management/commands/geoplaces_import_osm.py`

Created comprehensive import command with the following features:

#### Command Structure

```bash
app geoplaces_import_osm europe/switzerland              # Import Switzerland
app geoplaces_import_osm europe/alps                     # Import Alps region
app geoplaces_import_osm --dry-run europe/switzerland    # Dry run
app geoplaces_import_osm -l 100 europe/switzerland       # Limit to 100 records
```

#### Features Implemented

**1. OSM Tag Mapping**

Maps OSM tags to category slugs:

```python
FOOD_SUPPLY_TAGS = {
    "shop=convenience": "food_supply.grocery",
    "shop=general": "food_supply.grocery",
    "shop=supermarket": "food_supply.supermarket",
    "shop=bakery": "food_supply.bakery",
    "shop=butcher": "food_supply.butcher",
    "shop=greengrocer": "food_supply.greengrocer",
    "shop=farm": "food_supply.farm_shop",
    "shop=deli": "food_supply.deli",
    "shop=cheese": "food_supply.cheese_shop",
    "shop=dairy": "food_supply.dairy",
    "shop=beverages": "food_supply.beverages",
    "amenity=vending_machine": "food_supply.vending_machine",
}
```

**2. PBF Download**

- Downloads from Geofabrik using `httpx`
- Shows progress every 10MB
- Stores in temporary directory
- Auto-cleanup after processing

**3. OSM Data Parsing**

Uses `osmium` library to parse PBF files:

- **OSMHandler**: Custom handler for extracting amenities
- **Nodes**: Point features (shops, vending machines)
- **Ways**: Polygon features (larger supermarkets)
- **Centroid calculation**: For way geometries

**4. Category Auto-Creation**

Automatically creates categories if they don't exist:

- Creates parent category (e.g., `food_supply`)
- Creates child category (e.g., `food_supply.supermarket`)
- Sets proper naming and relationships

**5. Deduplication Logic (WEP008)**

Three-tier deduplication strategy:

```python
1. OSM source + source_id
   - If already imported, update in place

2. Location + category parent (50m radius)
   - Same category family within 50 meters
   - Single match → update
   - Multiple matches → mark for review

3. Location only (10m radius)
   - Any place within 10 meters
   - Single match → update
   - Multiple matches → mark for review
```

**6. Upsert Logic**

Creates or updates `GeoPlace` + `AmenityDetail`:

- Respects `protected_fields` (won't overwrite manual edits)
- Stores all OSM tags in `osm_tags` field
- Parses opening hours (basic implementation)
- Formats phone numbers
- Creates `GeoPlaceSourceAssociation` with:
  - `source_id`: `{osm_type}/{osm_id}` (e.g., `node/123456`)
  - `priority`: 1 (OSM has high priority)
  - `modified_date`: Current import timestamp
  - `import_date`: First import timestamp

**7. Website Handling**

Websites are stored via `ExternalLink` model:

- Creates or gets existing `ExternalLink`
- Associates with `GeoPlace` via `GeoPlaceExternalLink`
- Sets link type category (`external_link.website`)
- Uses place name as default label

**8. Cleanup (Two-Pass Import)**

After upserting all current records:

- Finds associations where `modified_date` < current run
- Deactivates places (`is_active=False`)
- Sets `review_status=review` for manual review
- This ensures deleted OSM places are handled

**9. Opening Hours Parsing**

Full implementation using `opening-hours-py` library (Rust-based):

```python
def _parse_opening_hours(self, opening_hours_str: str | None) -> dict:
    """Parse OSM opening_hours format to structured weekly format."""
    if not opening_hours_str:
        return {}

    try:
        from opening_hours import OpeningHours
        oh = OpeningHours(opening_hours_str)

        # Sample every 30 minutes to detect open/closed periods
        result = {}
        for weekday in ["monday", "tuesday", ..., "sunday"]:
            intervals = []
            # Check if open at each 30-min interval
            # Build intervals: [{"open": "08:00", "close": "12:00"}, ...]
            result[weekday] = intervals

        result["_raw"] = opening_hours_str  # Store original for reference
        return result
    except Exception:
        return {"_raw": opening_hours_str}  # Fallback
```

**Example output**:
```json
{
    "monday": [{"open": "08:00", "close": "12:00"}, {"open": "14:00", "close": "18:00"}],
    "tuesday": [{"open": "08:00", "close": "18:00"}],
    "wednesday": [{"open": "08:00", "close": "18:00"}],
    "_raw": "Mo-Fr 08:00-12:00,14:00-18:00; Sa 08:00-12:00"
}
```

---

## Data Flow

```
1. Download PBF
   ↓
2. Parse with osmium
   ↓
3. Extract amenities (nodes + ways)
   ↓
4. For each amenity:
   ├─ Find existing place (deduplication)
   ├─ Get/create category
   ├─ Parse opening_hours
   ├─ Create/update GeoPlace
   ├─ Create/update AmenityDetail
   ├─ Create/update SourceAssociation
   └─ Add ExternalLink (if website exists)
   ↓
5. Cleanup deleted places
   ↓
6. Summary report
```

---

## Models Involved

### GeoPlace
- `name`: Place name
- `location`: Point geometry
- `place_type`: Category FK
- `country_code`: Country code (currently hardcoded to "CH")
- `detail_type`: "amenity"
- `osm_tags`: Raw OSM tags (JSON)
- `review_status`: "new" for imported places
- `protected_fields`: Auto-populated on manual edits

### AmenityDetail
- `geo_place`: OneToOne FK to GeoPlace
- `operating_status`: "open" by default
- `opening_hours`: Parsed hours (JSON)
- `phones`: Phone numbers (JSON array)

### GeoPlaceSourceAssociation
- `place`: FK to GeoPlace
- `organization`: FK to Organization (OSM)
- `source_id`: "{osm_type}/{osm_id}"
- `import_date`: First import timestamp
- `modified_date`: Last update timestamp
- `priority`: 1 (OSM priority)
- `update_policy`: "always" (default)
- `delete_policy`: "deactivate" (default)

### ExternalLink (via GeoPlaceExternalLink)
- `url`: Website URL
- `label`: Place name (default)
- `link_type`: Category FK ("external_link.website")

---

## Known Limitations & TODOs

### 1. Opening Hours Parsing
**Status**: ✅ **Implemented**  
Uses `opening-hours-py` library to parse OSM opening_hours format into structured weekly format with open/close intervals per day.

### 2. Country Code Detection
**Current**: Hardcoded to "CH" (Switzerland)  
**TODO**: Implement proper country lookup via:
- Shapefile/GeoJSON boundaries
- Reverse geocoding API
- Extract from PBF file path

### 3. PBF Filtering
**Current**: Parses entire PBF, filters in Python  
**TODO**: Consider using `osmium tags-filter` to pre-filter PBF:

```bash
osmium tags-filter input.pbf \
    nwr/shop=convenience,supermarket,bakery,butcher,greengrocer,farm,deli,cheese,dairy,beverages \
    nwr/amenity=vending_machine \
    -o filtered.pbf
```

This would reduce memory usage and speed up parsing.

### 4. Missing Migration
**Status**: `websites` field removed from AmenityDetail  
**TODO**: Create migration to drop the field:

```bash
app makemigrations geometries --name remove_websites_from_amenitydetail
```

Currently blocked by unrelated `ExternalLink.identifier` migration issue.

### 5. Vending Machine Filtering
**Current**: Checks `vending` tag for food/drinks/sweets/coffee  
**TODO**: Verify this covers all food-related vending machines

### 6. Category Parent Creation
**Current**: Creates categories on-the-fly  
**TODO**: Consider pre-seeding common categories via fixture

### 7. Error Handling
**Current**: Basic try/catch with error logging  
**TODO**: Improve error handling for:
- Download failures (retry logic)
- Parse errors (skip invalid records)
- Database errors (rollback and continue)

### 8. Progress Reporting
**Current**: Prints progress every 100 records  
**TODO**: Use `rich` library for better progress bars

---

## Testing Strategy

### Unit Tests Needed

```python
# tests/test_osm_import.py

def test_osm_tag_mapping():
    """Test OSM tag to category slug mapping"""

def test_category_creation():
    """Test auto-creation of parent/child categories"""

def test_deduplication_exact_match():
    """Test finding existing place by source_id"""

def test_deduplication_nearby():
    """Test finding existing place by location"""

def test_opening_hours_parsing():
    """Test parsing various opening_hours formats"""

def test_phone_formatting():
    """Test formatting phone numbers (single and multiple)"""
```

### Integration Testing

```bash
# Test with small region
app geoplaces_import_osm --dry-run -l 50 europe/liechtenstein

# Test with actual import
app geoplaces_import_osm -l 100 europe/liechtenstein

# Verify database
app shell
>>> from server.apps.geometries.models import GeoPlace
>>> GeoPlace.objects.filter(detail_type='amenity').count()
>>> GeoPlace.objects.filter(place_type__slug__startswith='food_supply').count()
```

---

## Usage Examples

### Import Switzerland Food Supply Amenities

```bash
# Dry run first
app geoplaces_import_osm --dry-run europe/switzerland

# Import first 1000 for testing
app geoplaces_import_osm -l 1000 europe/switzerland

# Full import
app geoplaces_import_osm europe/switzerland
```

### Import Alps Region

```bash
app geoplaces_import_osm europe/alps
```

### Check Import Results

```python
from server.apps.geometries.models import GeoPlace
from server.apps.categories.models import Category

# Count imported amenities
amenity_count = GeoPlace.objects.filter(detail_type='amenity').count()
print(f"Total amenities: {amenity_count}")

# Count by category
food_categories = Category.objects.filter(slug__startswith='food_supply')
for cat in food_categories:
    count = GeoPlace.objects.filter(place_type=cat).count()
    print(f"{cat.slug}: {count}")

# Check OSM source
from server.apps.organizations.models import Organization
osm_org = Organization.objects.get(slug='osm')
osm_places = GeoPlace.objects.filter(source_set=osm_org).count()
print(f"Places from OSM: {osm_places}")
```

---

## System Requirements

### Python Packages (Already Added)
- `osmium>=3.7.0`
- `httpx>=0.27.0`
- `opening-hours>=0.1.0`

### System Libraries (Required)
Install via system package manager:

**Ubuntu/Debian**:
```bash
sudo apt-get install libosmium2-dev
```

**macOS**:
```bash
brew install osmium-tool
```

**Docker** (add to Dockerfile):
```dockerfile
RUN apt-get update && apt-get install -y libosmium2-dev
```

---

## Performance Considerations

### Memory Usage

- **PBF Size**: Switzerland ~500MB, Alps ~5GB
- **Parsed Amenities**: ~10,000-50,000 objects in memory
- **Recommendation**: Process in batches for very large regions

### Processing Time

Estimated times (single-threaded):

| Region | PBF Size | Amenities | Time |
|--------|----------|-----------|------|
| Liechtenstein | 10MB | ~500 | ~30s |
| Switzerland | 500MB | ~15,000 | ~5min |
| Alps | 5GB | ~100,000 | ~45min |

**Optimization opportunities**:
1. Pre-filter PBF with `osmium tags-filter`
2. Batch database inserts (currently one-by-one)
3. Parallel processing for multiple regions
4. Cache category lookups

---

## Related WEPs

- **WEP008**: GeoPlace Extensions & Amenity Import (specification)
- **WEP003**: GTFS Integration (future transport imports)

---

## Next Steps

1. **Test with small dataset** (Liechtenstein or small canton)
2. **Fix migration issue** (websites field removal)
3. **Improve opening_hours parsing** (structured format)
4. **Add country code detection** (shapefile or API)
5. **Pre-filter PBF files** (osmium tags-filter)
6. **Add progress bars** (rich library)
7. **Create fixtures** (common food_supply categories)
8. **Write unit tests** (tag mapping, deduplication, parsing)
9. **Document deployment** (system dependencies, cron jobs)
10. **Expand to other amenity types** (restaurants, emergency, accommodation)

---

## Summary

The OSM import command is **feature-complete** for basic food supply amenity imports:

✅ Downloads PBF files from Geofabrik  
✅ Parses OSM data (nodes + ways)  
✅ Maps OSM tags to categories  
✅ Auto-creates categories  
✅ Deduplicates against existing places  
✅ Creates GeoPlace + AmenityDetail  
✅ Stores OSM tags for debugging  
✅ Handles websites via ExternalLink  
✅ Formats phone numbers  
✅ Parses opening hours to structured format (using opening-hours-py)  
✅ Cleans up deleted places  
✅ Two-pass import strategy  
✅ Dry-run support  
✅ Progress reporting  

**Ready for testing with small datasets!**

### Recent Updates

**2026-03-07 - Opening Hours Parsing Enhancement**
- Updated to use `opening-hours-py>=1.1.6` (Rust-based library)
- Implemented full parsing from OSM format to structured weekly format
- Samples every 30 minutes to detect open/closed periods
- Stores original raw string in `_raw` field for reference
- Gracefully handles parse errors with fallback to raw storage

The command follows Django best practices, WEP008 specifications, and existing codebase patterns (similar to `import_geoplaces`).
