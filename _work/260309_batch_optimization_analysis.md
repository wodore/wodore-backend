# Batch Size Optimization Analysis

**Date:** 2026-03-09

## Test Results Summary

### Current Performance (1,000 places)

| Approach | Time per Place | Total Time | Speedup |
|----------|----------------|------------|---------|
| Individual saves | 23.00ms | 23.0s | 1x (baseline) |
| **Hybrid dedup + bulk** | **5.76ms** | **5.76s** | **4.0x faster** |

### Key Insight

The hybrid approach achieves:
- ✅ **4x speedup** over individual saves
- ✅ **Keeps deduplication** (only 7 duplicates created out of 1000)
- ✅ **1.6 hours for 1M places** (vs 6.4 hours)

---

## Batch Size Optimization

Let's test different batch sizes to find the sweet spot:

| Batch Size | Expected Time per Place | Trade-offs |
|------------|------------------------|------------|
| 50 | ~6ms | More transactions, less memory |
| 100 | ~5.76ms | **Current - good balance** |
| 200 | ~5.5ms | Fewer transactions, more memory |
| 500 | ~5.2ms | Optimal speed, more memory |
| 1000 | ~5.0ms | Max speed, high memory usage |

### Recommendation: **Batch size 200-500**

**Why:**
- 200-500 gives the best speedup (4.5-5x)
- Memory usage still manageable (100-200 places in memory)
- Fewer database roundtrips
- Better progress granularity than 1000

---

## Additional Optimizations Identified

### 1. **Pre-fetch Related Objects** 🚀

**Current issue:** Category lookup for each place

```python
# SLOW: Queries category for each place
for place in places:
    category = Category.objects.get(identifier=schema.place_type_identifier)
```

**Optimization:**

```python
# FAST: Pre-fetch all categories once
categories = Category.objects.filter(
    identifier__in=[schema.place_type_identifier for schema in schemas]
)
category_cache = {cat.identifier: cat for cat in categories}

# Use cache
for place in places:
    category = category_cache[schema.place_type_identifier]
```

**Expected gain:** 1-2ms per place (5-10% faster)

---

### 2. **Bulk Source Association Check** 🚀

**Current issue:** Individual source_id lookups

```python
# SLOW: Individual queries
for schema in schemas:
    existing = GeoPlaceSourceAssociation.objects.get(
        organization=osm_org,
        source_id=source.source_id
    )
```

**Optimization:**

```python
# FAST: Single query for all source_ids
source_ids = [source.source_id for source in sources]
existing_associations = GeoPlaceSourceAssociation.objects.filter(
    organization=osm_org,
    source_id__in=source_ids
).select_related('geo_place')

existing_cache = {
    assoc.source_id: assoc.geo_place
    for assoc in existing_associations
}

# Check cache
for schema, source in zip(schemas, sources):
    existing = existing_cache.get(source.source_id)
```

**Expected gain:** 2-3ms per place (10-15% faster)

---

### 3. **Parallel Batch Processing** 🚀

**Current issue:** Sequential batch processing

```python
# SLOW: One batch at a time
for batch in batches:
    process_batch(batch)  # 5.76ms per place
```

**Optimization:**

```python
# FAST: Process 2-3 batches in parallel
from concurrent.futures import ThreadPoolExecutor

def process_batch(batch):
    # Dedup + bulk create
    return process_hybrid(batch)

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = []
    for batch in batches:
        futures.append(executor.submit(process_batch, batch))

    # Collect results
    for future in futures:
        future.result()
```

**Expected gain:** 2-3x faster (with 3 workers)

---

### 4. **Optimize Slug Generation Further** 🚀

**Current issue:** Still generating slugs individually

```python
# Could be faster for bulk
def generate_slugs_bulk(names):
    """Generate slugs for multiple names at once."""
    base_slugs = [create_base_slug(name) for name in names]
    uuids = [generate_uuid(len(slug)) for slug in base_slugs]
    return [f"{base}-{uuid}" for base, uuid in zip(base_slugs, uuids)]
```

**Expected gain:** 0.1-0.2ms per place (minimal)

---

### 5. **Use `bulk_create` with `ignore_conflicts`** 🚀

**For new datasets only** (no duplicates):

```python
# Skip deduplication entirely for trusted sources
GeoPlace.objects.bulk_create(
    places,
    batch_size=500,
    ignore_conflicts=True,  # Skip on slug collision
    update_fields=[...]     # Or update specific fields
)
```

**Expected gain:** 3-4ms per place (but loses deduplication)

---

## Combined Optimization Potential

### Current: Hybrid Approach (5.76ms per place)

```
1. Dedup check (BBox): 0.52ms
2. Individual saves: 5.24ms
```

### With All Optimizations (Estimated: 2-3ms per place)

```
1. Pre-fetched categories: -0.5ms
2. Bulk source check: -1.0ms
3. Larger batch size (500): -0.5ms
4. Parallel processing (3x): -2.0ms
```

**Expected result: 2-3ms per place = 8-10x faster than individual saves!**

---

## Implementation Priority

### Phase 1: Quick Wins (1-2 hours)
1. ✅ **Hybrid dedup + bulk** - Already tested (4x faster)
2. ⏳ **Increase batch size to 500** - Simple change
3. ⏳ **Pre-fetch categories** - Add cache

**Expected: 5x faster** (1M places in 1.3 hours)

### Phase 2: Medium Effort (2-4 hours)
4. ⏳ **Bulk source association check** - Single query
5. ⏳ **Optimize slug generation** - Batch processing

**Expected: 6x faster** (1M places in 1.1 hours)

### Phase 3: Advanced (4-8 hours)
6. ⏳ **Parallel batch processing** - ThreadPoolExecutor
7. ⏳ **Async database operations** - Django async

**Expected: 8-10x faster** (1M places in 40-60 minutes)

---

## Memory vs Speed Trade-off

| Batch Size | Speed | Memory Usage | Recommendation |
|------------|-------|--------------|----------------|
| 50 | 3.5x | Low | Memory-constrained systems |
| 100 | 4.0x | Low-Medium | **Current** |
| 200 | 4.5x | Medium | **Recommended** |
| 500 | 5.0x | Medium-High | **Best for speed** |
| 1000 | 5.2x | High | Risk of OOM on large datasets |

---

## Final Recommendation

### For Switzerland (10k places)
- **Batch size: 500**
- **Expected time:** 1.5 minutes (vs 6 minutes individual)

### For Europe (500k places)
- **Batch size: 500**
- **Parallel processing: 3 workers**
- **Expected time:** 45 minutes (vs 3 hours individual)

### For Worldwide (5M places)
- **Batch size: 200** (conservative)
- **Parallel processing: 4 workers**
- **Expected time:** 6 hours (vs 32 hours individual)

---

## Next Steps

1. **Test different batch sizes:**
   ```bash
   # Add batch size parameter to test
   app test_import_performance --test hybrid --batch-size 200 --iterations 1000
   ```

2. **Implement Phase 1 optimizations:**
   - Increase batch size to 500
   - Add category pre-fetching
   - Add bulk source check

3. **Benchmark with real data:**
   ```bash
   # Test with 1000 real places
   time app geoplaces_import_osm --overpass CH -l 1000
   ```

4. **Monitor and tune:**
   - Memory usage during import
   - Database connection pool
   - Progress update frequency

---

## Summary

✅ **Hybrid approach: 4x faster** (proven)
✅ **Batch size 500: 5x faster** (estimated)
✅ **With all optimizations: 8-10x faster** (theoretical)

**Realistic target:** 1M places in **1-1.5 hours** (vs 6.4 hours currently)

**Key insight:** The hybrid approach gives you bulk operation speed while keeping deduplication safety. This is the sweet spot for OSM imports!
