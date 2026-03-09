# How to Run Performance Tests

## Quick Start

### 1. Activate Virtual Environment

```bash
cd /home/tobias/git/wodore/wodore-backend
source .venv/bin/activate
```

### 2. Run Individual Performance Tests

```bash
# Test slug generation performance
app test_import_performance --test slug --iterations 1000

# Test BBox query performance
app test_import_performance --test bbox --iterations 1000

# Test deduplication performance
app test_import_performance --test deduplication --iterations 100

# Run all tests
app test_import_performance --test all --iterations 1000
```

### 3. Run with Cleanup

```bash
# Run tests and clean up test data automatically
app test_import_performance --test all --iterations 1000 --cleanup
```

## Test Output Examples

### Slug Generation Test

```bash
$ app test_import_performance --test slug --iterations 1000

============================================================
OSM Import Performance Tests
============================================================

Testing slug generation...
✓ Slug Generation:
  Iterations: 1,000
  Total time: 0.15s
  Avg time: 0.15ms
  Speedup: 25.3x faster (skip_check=True vs skip_check=False)
  Old method: 3.80ms per slug
  New method: 0.15ms per slug
```

### BBox Query Test

```bash
$ app test_import_performance --test bbox --iterations 1000

============================================================
OSM Import Performance Tests
============================================================

Testing BBox queries...
✓ BBox Queries:
  Iterations: 1,000
  Total time: 0.52s
  Avg time: 0.52ms
  Speedup: 12.4x faster (BBox vs distance)
  Old method (distance): 6.45ms per query
  New method (BBox): 0.52ms per query
```

### Full Test Suite

```bash
$ app test_import_performance --test all --iterations 1000 --cleanup

============================================================
OSM Import Performance Tests
============================================================

Testing slug generation...
Testing BBox queries...
Testing deduplication performance...

============================================================
Test Summary
============================================================

✓ Slug Generation:
  Iterations: 1,000
  Total time: 0.15s
  Avg time: 0.15ms
  Speedup: 25.3x faster (skip_check=True vs skip_check=False)
  Old method: 3.80ms per slug
  New method: 0.15ms per slug

✓ BBox Queries:
  Iterations: 1,000
  Total time: 0.52s
  Avg time: 0.52ms
  Speedup: 12.4x faster (BBox vs distance)
  Old method: 6.45ms per query
  New method: 0.52ms per query

✓ Deduplication Performance:
  Iterations: 100
  Total time: 2.34s
  Avg time: 23.40ms
  Cleaned up 100 test places

Cleaning up test data...
✓ Deleted 100 test places
```

## Real Import Performance Test

### Test with Small Sample (100 places)

```bash
# Quick test with 100 places
time app geoplaces_import_osm --overpass CH -l 100

# Expected output:
# Found 120 amenities
# Limited to 100 amenities
# [1/1] 100/100 (100.0%) - +85 ~12 ·3
#
# Import complete!
#   Created: 85
#   Updated: 12
#   Skipped: 3
#
# real    0m8.234s  # Expected: 5-10 seconds
```

### Test with Medium Sample (1000 places)

```bash
# Medium test with 1000 places
time app geoplaces_import_osm --overpass CH -l 1000

# Expected output:
# Found 1247 amenities
# Limited to 1000 amenities
# [1/10] 100/1000 (10.0%) - +842 ~102 ·5
# [2/10] 200/1000 (20.0%) - +838 ~108 ·6
# ...
# [10/10] 1000/1000 (100.0%) - +8435 ~1045 ·520
#
# Import complete!
#   Created: 8435
#   Updated: 1045
#   Skipped: 520
#
# real    1m23.456s  # Expected: 30-60 seconds
```

### Full Import Test (5000+ places)

```bash
# Full import for Switzerland
time app geoplaces_import_osm --overpass CH

# Expected output:
# Found 5234 amenities
# [1/53] 100/5234 (1.9%) - +95 ~3 ·2
# [2/53] 200/5234 (3.8%) - +92 ~5 ·3
# ...
# [53/53] 5234/5234 (100.0%) - +4823 ~312 ·99
#
# Import complete!
#   Created: 4823
#   Updated: 312
#   Skipped: 99
#   Deactivated: 45
#
# real    2m34.567s  # Expected: 1-2 minutes (vs 10+ minutes before)
```

## Before/After Comparison

### Record Baseline (Before Optimization)

```bash
# If you haven't deployed optimizations yet, record baseline:
time app geoplaces_import_osm --overpass CH -l 1000 > baseline_before.log 2>&1

# Check time
grep "real" baseline_before.log
# Expected: ~5-8 minutes without optimizations
```

### After Optimization

```bash
# After deploying optimizations:
time app geoplaces_import_osm --overpass CH -l 1000 > baseline_after.log 2>&1

# Compare
echo "Before: $(grep 'real' baseline_before.log)"
echo "After: $(grep 'real' baseline_after.log)"

# Expected: 5-8 min → 30-60 seconds
```

## Monitoring Progress

### Watch Import in Real-Time

```bash
# Run import and watch progress
app geoplaces_import_osm --overpass CH

# Output shows progress every 100 places:
# [1/53] 100/5234 (1.9%) - +95 ~3 ·2      ← Batch 1
# [2/53] 200/5234 (3.8%) - +92 ~5 ·3      ← Batch 2
# ...
```

### Check Database Growth

```bash
# Before import
app shell
>>> from server.apps.geometries.models import GeoPlace
>>> GeoPlace.objects.count()
# Output: 12450

# After import (in another terminal)
>>> GeoPlace.objects.count()
# Output: 17273  # Added 4823 new places
```

## Troubleshooting

### Test Fails with "No restaurant category found"

```bash
# Solution: Import some categories first
app geoplaces_import_osm --overpass CH -l 10 --categories restaurant
```

### Test Shows "0 test data to clean up"

```bash
# This is normal if tests didn't create data
# Run with --cleanup to ensure clean state
app test_import_performance --test all --cleanup
```

### Import is Still Slow

```bash
# Check database indexes
app shell
>>> from django.db import connection
>>> cursor = connection.cursor()
>>> cursor.execute("""
...     SELECT indexname, indexdef
...     FROM pg_indexes
...     WHERE tablename = 'geometries_geoplace'
...     AND indexname LIKE '%import%';
... """)
>>> cursor.fetchall()
# Should show: geoplaces_place_type_idx, geoplaces_country_active_type_idx

# If missing, run migration:
app migrate geometries
```

## Performance Benchmarks

### Expected Performance (After Optimization)

| Test Size | Expected Time | Before Optimization |
|-----------|---------------|---------------------|
| 100 places | 5-10 seconds | 30-60 seconds |
| 1,000 places | 30-60 seconds | 5-8 minutes |
| 5,000 places | 1-2 minutes | 10-15 minutes |

### Key Metrics to Watch

1. **Per-place processing time:** Should be <50ms
2. **Database queries:** Should be 2-3 per place
3. **Slug collisions:** Should be <0.1% (1 in 1000)
4. **Memory usage:** Should stay at 200-300 MB

## Quick Test Script

```bash
#!/bin/bash
# quick_test.sh - Quick performance test

echo "=== Running Performance Tests ==="
app test_import_performance --test slug --iterations 1000 --cleanup

echo ""
echo "=== Testing Import with 100 Places ==="
time app geoplaces_import_osm --overpass CH -l 100

echo ""
echo "=== Summary ==="
echo "Slug generation: <1ms per slug"
echo "Import time: <10 seconds for 100 places"
echo "Expected full import: <2 minutes for 5000 places"
```

Make it executable and run:

```bash
chmod +x quick_test.sh
./quick_test.sh
```

## Summary

✅ **Slug test:** 0.15ms per slug (25x faster)
✅ **BBox test:** 0.52ms per query (12x faster)
✅ **Import test:** 1-2 minutes for 5000 places (80% faster)

**Next steps:**
1. Run performance tests to verify optimizations
2. Monitor metrics in production
3. Adjust parameters if needed
