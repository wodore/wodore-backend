# OSM Import Fixes

**Date**: 2026-03-07  
**Status**: Fixes Required

---

## Issues Found

### 1. Database Error: `websites` field still exists
```
null value in column "websites" of relation "geometries_amenitydetail" violates not-null constraint
```

**Root Cause**: The `websites` field was removed from the model code but the migration hasn't been applied yet.

**Fix**: Apply migration 0014:
```bash
app migrate geometries 0014_remove_amenitydetail_websites
```

**Migration file already created**: `server/apps/geometries/migrations/0014_remove_amenitydetail_websites.py`

---

### 2. Missing Features: Download Caching & Performance

**Issues**:
- PBF files are re-downloaded every time (slow for testing)
- No pre-filtering of OSM data (parsing entire file is slow)
- "Parsing OSM data..." takes too long

---

## Required Code Changes

### Change 1: Add `--data-dir` argument (Already Done)

This has been added to the command arguments.

### Change 2: Implement download caching

Replace `_download_pbf()` method with `_get_or_download_pbf()`:

```python
def _get_or_download_pbf(self, region: str, data_dir: str | None) -> Path:
    """Get existing PBF file or download if not present."""
    # Determine storage directory
    if data_dir:
        storage_dir = Path(data_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
        cleanup_after = False  # Don't delete if using persistent dir
    else:
        storage_dir = Path(tempfile.mkdtemp())
        cleanup_after = True

    filename = f"{region.replace('/', '_')}.osm.pbf"
    pbf_path = storage_dir / filename

    # Check if file already exists
    if pbf_path.exists():
        self.stdout.write(self.style.SUCCESS(f"Using cached PBF: {pbf_path}"))
        self._cleanup_after = cleanup_after
        self._storage_dir = storage_dir
        return pbf_path

    # Download if not exists
    self.stdout.write(f"Downloading from Geofabrik...")
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"

    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(pbf_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total and downloaded % (1024 * 1024 * 10) == 0:  # Every 10MB
                        progress = (downloaded / total) * 100
                        self.stdout.write(f"  Progress: {progress:.1f}%")

        self._cleanup_after = cleanup_after
        self._storage_dir = storage_dir
        return pbf_path

    except Exception as e:
        self.stdout.write(self.style.ERROR(f"Download failed: {e}"))
        if cleanup_after:
            storage_dir.rmdir()
        return Path()
```

### Change 3: Update `handle()` method

```python
def handle(self, *args, **options):
    """Main command execution."""
    region = options["region"]
    dry_run = options["dry_run"]
    limit = options.get("limit")
    data_dir = options.get("data_dir")  # ADD THIS
    run_start = timezone.now()

    self.stdout.write(f"Importing OSM amenities from {region}...")

    if dry_run:
        self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

    # 1. Get or download PBF file
    self.stdout.write("Locating PBF file...")
    pbf_path = self._get_or_download_pbf(region, data_dir)  # CHANGE THIS

    if not pbf_path.exists():
        self.stdout.write(self.style.ERROR(f"Failed to get PBF file for {region}"))
        return

    # ... rest of the code ...

    # Cleanup temp file (only if using temp dir)
    if hasattr(self, '_cleanup_after') and self._cleanup_after:
        pbf_path.unlink()
        if hasattr(self, '_storage_dir'):
            self._storage_dir.rmdir()
```

### Change 4: Pre-filter PBF with osmium tags-filter (Optional - Big Performance Improvement)

Add a new method to pre-filter the PBF file:

```python
import subprocess
import shutil

def _filter_pbf(self, input_pbf: Path) -> Path:
    """Filter PBF to only food supply amenities using osmium."""
    # Check if osmium-tool is available
    if not shutil.which("osmium"):
        self.stdout.write(self.style.WARNING(
            "osmium-tool not found - parsing entire PBF (slower). "
            "Install with: sudo apt-get install osmium-tool"
        ))
        return input_pbf

    # Create filtered file path
    filtered_pbf = input_pbf.parent / f"{input_pbf.stem}_filtered.osm.pbf"

    # Skip if filtered file already exists
    if filtered_pbf.exists():
        self.stdout.write(f"Using cached filtered PBF: {filtered_pbf}")
        return filtered_pbf

    self.stdout.write("Pre-filtering PBF with osmium (this speeds up parsing)...")

    # Build filter expression for food supply tags
    filters = [
        'nwr/shop=convenience',
        'nwr/shop=general',
        'nwr/shop=supermarket',
        'nwr/shop=bakery',
        'nwr/shop=butcher',
        'nwr/shop=greengrocer',
        'nwr/shop=farm',
        'nwr/shop=deli',
        'nwr/shop=cheese',
        'nwr/shop=dairy',
        'nwr/shop=beverages',
        'nwr/amenity=vending_machine',
    ]

    try:
        cmd = [
            'osmium',
            'tags-filter',
            str(input_pbf),
            *filters,
            '-o', str(filtered_pbf),
            '--overwrite',
        ]

        subprocess.run(cmd, check=True, capture_output=True)
        self.stdout.write(self.style.SUCCESS(f"Filtered PBF created: {filtered_pbf}"))
        return filtered_pbf

    except subprocess.CalledProcessError as e:
        self.stdout.write(self.style.WARNING(
            f"Filtering failed: {e}. Using unfiltered PBF."
        ))
        return input_pbf
    except Exception as e:
        self.stdout.write(self.style.WARNING(
            f"Filtering error: {e}. Using unfiltered PBF."
        ))
        return input_pbf
```

Then update the parsing section in `handle()`:

```python
# 2. Filter PBF file (optional but recommended for performance)
pbf_to_parse = self._filter_pbf(pbf_path)

# 3. Parse PBF file
self.stdout.write("Parsing OSM data...")
handler = OSMHandler()
handler.apply_file(str(pbf_to_parse))  # Use filtered file
amenities = handler.amenities
```

---

## Testing After Fixes

### Step 1: Apply Migration

```bash
# Make sure database is running
docker compose up -d postgres

# Apply migration
app migrate geometries 0014
```

### Step 2: Test with Cached Downloads

```bash
# Create data directory
mkdir -p /tmp/osm_data

# First run (downloads and caches)
app geoplaces_import_osm --data-dir /tmp/osm_data -l 10 europe/liechtenstein

# Second run (uses cache - should be much faster)
app geoplaces_import_osm --data-dir /tmp/osm_data -l 10 europe/liechtenstein
```

### Step 3: Test with Pre-filtering (Requires osmium-tool)

```bash
# Install osmium-tool
sudo apt-get install osmium-tool

# Run import (will create filtered PBF and cache it)
app geoplaces_import_osm --data-dir /tmp/osm_data -l 100 europe/switzerland

# Check that filtered file was created
ls -lh /tmp/osm_data/
# Should see both:
# - europe_switzerland.osm.pbf (original, ~500MB)
# - europe_switzerland_filtered.osm.pbf (filtered, much smaller)
```

---

## Performance Improvements

### Before
- **Download**: Every time (~2-5 min for Switzerland)
- **Parse**: Full PBF file (~3-5 min for Switzerland)
- **Total**: ~5-10 min per run

### After (with both optimizations)
- **Download**: Once, then cached (0 sec on subsequent runs)
- **Filter**: Once, then cached (~30 sec, then 0 sec)
- **Parse**: Filtered file only (~10-30 sec vs 3-5 min)
- **Total First Run**: ~5-6 min
- **Total Subsequent Runs**: ~10-30 sec ⚡

---

## Example Usage

```bash
# Create persistent data directory
mkdir -p ~/osm_data

# First import (slow - downloads and filters)
app geoplaces_import_osm --data-dir ~/osm_data europe/switzerland

# Subsequent imports (fast - uses cached files)
app geoplaces_import_osm --data-dir ~/osm_data europe/switzerland

# Test with small region first
app geoplaces_import_osm --data-dir ~/osm_data -l 50 europe/liechtenstein

# Dry run to see what would be imported
app geoplaces_import_osm --data-dir ~/osm_data --dry-run europe/switzerland
```

---

## Summary of Required Actions

1. ✅ **Migration already created** - Just needs to be applied
2. ⏳ **Code changes needed** - Implement caching and filtering
3. 📦 **Optional**: Install osmium-tool for pre-filtering

Let me know when the migration is applied and I can provide the complete updated command file!
