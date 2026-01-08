# External GeoNames App

This Django app provides integration with GeoNames geographic data as a raw, external source. It follows the separation principle: external source data remains immutable and separate from curated domain models.

## Architecture

### Models

- **Feature** - Curated configuration for GeoNames feature codes (enabled/disabled, importance weights)
- **GeoName** - Raw GeoNames point data (places, peaks, lakes, stations, etc.)
- **AlternativeName** - Multilingual names for GeoNames (separate table with foreign key)
- **Boundary** - GeoNames administrative boundaries (polygons for countries, states, districts, communes)

### Key Features

- **Bulk Operations** - Optimized imports using bulk_create/bulk_update (10-50x faster than individual operations)
- **Relational Structure** - AlternativeName as proper table instead of JSON for better querying
- **Hierarchical Data** - Parent-child relationships between places and administrative divisions
- **Administrative Boundaries** - MultiPolygon geometries for administrative divisions
- **Country Groups** - Support for named groups like "alps" for multi-country imports

## Management Commands

### import_features

Imports GeoNames feature codes from featureCodes_en.txt. Automatically run during migrations.

```bash
# Import/update feature codes
app import_features

# Use custom URL
app import_features --url https://example.com/featureCodes_en.txt
```

**Migration:** Features are automatically loaded via migration `0002_load_features.py`, and 75 outdoor/hiking-relevant features are enabled in `0003_enable_key_features.py`.

### import_geonames

Imports place data for specified countries using bulk operations for optimal performance.

```bash
# Import for all Alpine countries (AT, CH, DE, FR, IT, LI, MC, SI)
app import_geonames -c alps

# Import for specific countries
app import_geonames -c ch,de,fr,it,at,li

# Drop existing CH data first, then import
app import_geonames -c ch --drop

# Drop all data, then import
app import_geonames -c ch,de --drop-all

# Test with limited records
app import_geonames -c ch --limit 1000

# Skip alternate names for faster import (testing)
app import_geonames -c ch --skip-altnames
```

**Data Sources:**

- Country data: `https://download.geonames.org/export/dump/{CC}.zip`
- Alternate names: `https://download.geonames.org/export/dump/alternatenames/{CC}.zip`

**Performance:** Uses bulk_create/bulk_update with batch size of 500 for optimal performance.

### import_hierarchy

Imports hierarchical relationships between places and their administrative divisions.

```bash
# Import hierarchy for all Alpine countries
app import_hierarchy -c alps

# Import hierarchy for specific countries
app import_hierarchy -c ch

# Clear existing hierarchy first
app import_hierarchy -c ch --clear
```

**What it does:**

1. **Downloads hierarchy.zip** - Imports explicit parent-child relationships (2,304 for CH)
   - Administrative divisions: Canton → District → Commune
   - University buildings hierarchy
2. **Builds admin code relationships** - Links all places to their administrative divisions (79,822 for CH)
   - Uses admin1_code, admin2_code, admin3_code to find most specific parent
   - Priority: ADM4 > ADM3 > ADM2 > ADM1
   - Links cities, mountains, lakes, etc. to their commune/district/canton

**Result:** ~99.6% of places have parent relationships showing their administrative location.

### import_boundaries

Imports administrative boundary polygons (shapes) from GeoNames.

```bash
# Import boundaries for all Alpine countries
app import_boundaries -c alps

# Import boundaries for specific countries  
app import_boundaries -c ch

# Drop existing CH boundaries first
app import_boundaries -c ch --drop

# Import only specific admin level
app import_boundaries -c ch --admin-level 1  # States/provinces only
```

**Data Source:** `https://download.geonames.org/export/dump/shapes_all_low.zip` (1.28 MB, 249 boundaries worldwide)

**Note:** The shapes_all_low.zip file contains primarily country-level boundaries. For more detailed boundaries (cantons, districts), a larger file would be needed.

## Admin Interface

All models are registered in Django admin with optimized views:

### Feature Admin

- **Editable** configuration (enable/disable, set importance)
- Filter by class, enabled status
- Search by code, name

### GeoName Admin

- **Read-only** view of imported places
- Displays: Feature, Name, Country, Parent, Location, Population, Enabled, Importance
- Filters: Deleted, Country, Feature class, Enabled, Importance range
- Search: Name, ASCII name, GeoName ID
- Inlines:
  - Alternative names (multilingual names)
  - Children (child places in hierarchy)
- Hierarchy display:
  - Parent column showing hierarchy type and parent name
  - Full hierarchy section in detail view

### AlternativeName Admin

- **Read-only** view of multilingual names
- Linked to parent GeoName
- Shows language, name variants, flags (preferred, short, colloquial, historic)

### Boundary Admin

- **Read-only** view of administrative boundaries
- Displays: GeoName ID, Name, Feature code, Admin level, Country

## Country Groups

The import commands support named country groups for convenience:

- **alps** - All countries touching the Alps: AT, CH, DE, FR, IT, LI, MC, SI

```bash
# Import all data for Alpine region
app import_geonames -c alps
app import_hierarchy -c alps
app import_boundaries -c alps
```

## Data Model Details

### GeoName Fields

- `geoname_id` - Unique GeoNames identifier (primary key)
- `name` - Primary name
- `ascii_name` - ASCII variant
- `feature` - Foreign key to Feature (class.code format, e.g., "T.PK")
- `parent` - Foreign key to parent GeoName (hierarchical relationship)
- `hierarchy_type` - Type of parent relationship (e.g., "ADM" for administrative)
- `location` - Point geometry (SRID 4326)
- `elevation` - Elevation in meters
- `population` - Population count
- `country_code` - ISO-3166 code
- `admin1_code` through `admin4_code` - Administrative division codes
- `timezone` - Timezone identifier
- `modification_date` - Last modification in GeoNames
- `is_deleted` - Deletion flag

### AlternativeName Fields

- `alternatename_id` - GeoNames alternate name ID (primary key)
- `geoname` - Foreign key to GeoName
- `iso_language` - Language code (ISO 639)
- `alternate_name` - Name in specific language
- `is_preferred_name` - Preferred name for this language
- `is_short_name` - Short name variant
- `is_colloquial` - Colloquial/informal name
- `is_historic` - Historic name

### Feature Fields

- `id` - Primary key in "CLASS.CODE" format (e.g., "T.PK")
- `feature_class` - Single letter class code (A, H, L, P, R, S, T, U, V)
- `feature_code` - Specific feature code (e.g., "PK", "PASS", "RSTN")
- `name` / `description` - Display information
- `is_enabled` - Include in future imports/processing
- `importance` - Importance score 0-100 (used for search ranking)
- `notes` - Internal curation notes

### Boundary Fields

- `geoname_id` - Reference to GeoName (primary key)
- `name` - Boundary name
- `feature_code` - Administrative level code (PCLI, ADM1, ADM2, ADM3, ADM4)
- `geometry` - MultiPolygon geometry (SRID 4326)
- `country_code` - ISO-3166 code
- `admin_level` - Numeric admin level (0=country, 1-4=subdivisions)

## Feature Configuration

75 outdoor/hiking-relevant features are enabled by default (via migration `0003_enable_key_features.py`):

**Terrain & Natural Features:**

- Mountains, peaks, hills, valleys, passes, glaciers
- Lakes, rivers, streams, waterfalls, springs
- Forests, vegetation, rocks, caves

**Infrastructure:**

- Train stations, cable cars, huts, campsites
- Roads, trails, parking areas, viewpoints

**Administrative & Populated Places:**

- Countries, cantons, districts, communes
- Cities, towns, villages

To modify feature configuration:

1. Go to Admin → External GeoNames → Features
2. Find the feature (e.g., `T.PK` for peaks)
3. Adjust enabled status and importance score (0-100)

## Administrative Hierarchy

The hierarchy system has two components:

### 1. Explicit Relationships (hierarchy.zip)

Parent-child relationships between administrative divisions:

```
Switzerland (PCLI)
└── Kanton Aargau (ADM1)
    └── Bezirk Aarau (ADM2)
        └── Aarau (ADM3 - commune)
```

### 2. Admin Code Relationships

Every place has admin codes that link it to its administrative location:

```
Aarau (city, PPLA)
- country_code: CH
- admin1_code: AG
- admin2_code: 1901  
- admin3_code: 4001
→ Links to: Aarau (commune, ADM3)
```

The import_hierarchy command automatically builds these relationships, so places like cities, mountains, and lakes are linked to their administrative divisions.

## Performance Optimization

All import commands use bulk operations for optimal performance:

- **Batch size:** 500 records per transaction
- **Bulk create/update:** 10-50x faster than individual operations
- **Pre-loaded lookups:** Admin divisions cached in memory for O(1) matching
- **Iterator chunks:** Memory-efficient processing of large datasets

**Typical import times for Switzerland (82,446 records):**

- GeoNames places: ~2-3 minutes
- Alternative names: ~1-2 minutes  
- Hierarchy: ~2-3 minutes
- Total: ~5-8 minutes

## Next Steps

After importing external data:

1. ✓ Features are configured (75 outdoor/hiking features enabled)
2. ✓ GeoNames data imported with hierarchy
3. ✓ Alternative names loaded for multilingual search
4. Create the `geoplace` app for curated domain models
5. Implement import pipeline from GeoName → GeoPlace
6. Add search functionality using alternative names
7. Implement importance-based ranking
8. Add OSM enrichment and routing capabilities

## Notes

- This app contains **raw, immutable** data from GeoNames
- Manual edits in admin are disabled for GeoName/AlternativeName/Boundary
- Only Feature configuration is editable
- Data is managed via management commands, not admin UI
- All import commands support the `-c alps` shortcut for Alpine countries
- ~99.6% of places have hierarchical parent relationships showing their administrative location
