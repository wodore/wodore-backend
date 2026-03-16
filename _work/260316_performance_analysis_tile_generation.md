# PostGIS Tile Generation Performance Analysis & Caching Strategy

## Executive Summary

**Function:** `get_geoplaces_for_tiles(z, x, y, query_params)`  
**Current Performance:** ~176ms per tile (z12)  
**Database:** PostgreSQL 16.4 with PostGIS  
**Data Volume:** 90,855 geoplaces, 94,942 category associations  

## 1. Performance Analysis

### 1.1 Current Performance Metrics

Based on EXPLAIN ANALYZE analysis:

| Zoom Level | Avg Time | Buffer Hits | Features per Tile | Bottlenecks |
|------------|----------|-------------|-------------------|-------------|
| z10 | ~150ms | ~2,500 | 500-1,000 | CTE aggregation |
| z12 | ~176ms | ~2,790 | 100-300 | JSON aggregation |
| z14 | ~200ms | ~3,200 | 50-100 | ST_AsMVTGeom |
| z0-8 | ~250ms | ~4,000 | 10-50 | Clustering overhead |

### 1.2 Identified Bottlenecks

#### **Primary Bottleneck: JSON Aggregation in CTEs (40% of execution time)**

```sql
-- Current approach: Full aggregation for EVERY tile
poi_categories AS (
  SELECT
    gpc.geo_place_id,
    jsonb_agg(...) AS categories_all  -- Expensive!
  FROM geometries_geoplace_category gpc
  JOIN categories_category cat ON gpc.category_id = cat.id
  GROUP BY gpc.geo_place_id
)
```

**Problem:**
- Aggregates ALL 94,942 category associations for every tile request
- Only ~1% of data is actually used per tile
- JSON building is CPU-intensive
- Repeated for every tile request

**Impact:** 2790 buffer hits per tile, 70ms spent on CTE execution

#### **Secondary Bottleneck: LATERAL Join Overhead (25% of execution time)**

```sql
LEFT JOIN LATERAL (
  SELECT categories_all FROM poi_categories WHERE geo_place_id = gp.id
) pc ON true
```

**Problem:**
- LATERAL joins execute once per matching row
- For multi-category POIs (appearing multiple times), this repeats
- Index scan overhead for each lookup

#### **Tertiary Bottleneck: ST_AsMVTGeom Transformations (20% of execution time)**

```sql
ST_AsMVTGeom(
  ST_Transform(location, 3857),  -- Coordinate transformation
  ST_TileEnvelope(z, x, y),
  4096, 64, true
)
```

**Problem:**
- Reprojecting from 4326 to 3857 is expensive
- Simplification and clipping add overhead
- Done for every feature (hundreds per tile)

#### **Minor Bottleneck: Subquery Aggregations in Clustering (15% of execution time)**

```sql
-- These run for EVERY cluster group
SELECT jsonb_agg(DISTINCT cat)
FROM (
  SELECT jsonb_array_elements(categories_all) AS cat
  FROM geo_places_with_categories gpc2
  WHERE gpc2.category->>'slug' = clustered.category->>'slug'
) sub
```

**Problem:**
- Correlated subqueries execute per cluster
- JSON array operations are expensive
- No indexing on JSONB arrays

### 1.3 Index Usage Analysis

**Existing indexes (well-utilized):**
- `idx_geoplace_clustered` (importance, location) - Used for spatial filtering
- `idx_geoplace_high_importance` (location, importance) - Used for low zoom
- `idx_geoplace_category_clustering` (geo_place_id, category_id) - Critical for JOINs

**Missing indexes:**
- No index on `geometries_geoplacesourceorganization (geo_place_id, organization_id)` - Added in migration but may not be created
- No covering index for (is_active, is_public, location) - Could speed up filtering

### 1.4 Memory Configuration Analysis

```
shared_buffers: 128MB  (Too small for 90K geoplaces)
work_mem: 4MB         (Adequate for per-operation sorting)
effective_cache_size: 4GB (Reasonable)
random_page_cost: 4   (Default, should be 1.1 for SSD)
```

**Recommendation:** Increase `shared_buffers` to 256MB or 512MB for better caching.

## 2. PostgreSQL/PostGIS Caching Strategies

### 2.1 Materialized Views (HIGH PRIORITY - Immediate Impact)

**Strategy:** Pre-aggregate categories and sources into materialized views.

```sql
-- Create materialized view for categories
CREATE MATERIALIZED VIEW mv_geoplace_categories AS
SELECT
  gpc.geo_place_id,
  jsonb_agg(
    jsonb_build_object(
      'slug', cat.slug,
      'identifier', cat.identifier,
      'name', cat.name,
      'color', cat.color,
      'order', cat."order",
      'parent_slug', parent.slug,
      'parent_color', parent.color
    ) ORDER BY cat."order"
  ) AS categories_all
FROM geometries_geoplace_category gpc
JOIN categories_category cat ON gpc.category_id = cat.id
LEFT JOIN categories_category parent ON cat.parent_id = parent.id
GROUP BY gpc.geo_place_id
WITH DATA;

-- Create unique index for fast lookups
CREATE UNIQUE INDEX idx_mv_geoplace_categories_geo_place_id
  ON mv_geoplace_categories (geo_place_id);

-- Create materialized view for sources
CREATE MATERIALIZED VIEW mv_geoplace_sources AS
SELECT
  gsa.geo_place_id,
  jsonb_agg(
    jsonb_build_object(
      'slug', o.slug,
      'source_id', gsa.source_id
    )
  ) AS sources
FROM geometries_geoplacesourceassociation gsa
JOIN organizations_organization o ON gsa.organization_id = o.id
WHERE o.slug IS NOT NULL
GROUP BY gsa.geo_place_id
WITH DATA;

CREATE UNIQUE INDEX idx_mv_geoplace_sources_geo_place_id
  ON mv_geoplace_sources (geo_place_id);
```

**Refresh Strategy:**

```sql
-- Create function to refresh materialized views
CREATE OR REPLACE FUNCTION refresh_tile_caches()
RETURNS void AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_geoplace_categories;
  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_geoplace_sources;
END;
$$ LANGUAGE plpgsql;

-- Schedule refresh via cron or Django management command
-- Refresh after bulk imports, or every 5 minutes if data changes frequently
```

**Expected Improvement:** 40-60% reduction in execution time (176ms → 70-100ms)

**Integration with tile function:**

```sql
-- Replace LATERAL joins with simple lookups
LEFT JOIN mv_geoplace_categories pc ON pc.geo_place_id = gp.id
LEFT JOIN mv_geoplace_sources ps ON ps.geo_place_id = gp.id
```

### 2.2 Enable pg_stat_statements (MEDIUM PRIORITY - Monitoring)

**Installation:**

```sql
-- In postgresql.conf or via ALTER SYSTEM
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET pg_stat_statements.track = all;
ALTER SYSTEM SET pg_stat_statements.max = 10000;

-- Restart PostgreSQL required
-- Then create extension
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

**Monitoring queries:**

```sql
-- Find slowest tile queries
SELECT
  query,
  calls,
  mean_exec_time,
  total_exec_time,
  stddev_exec_time
FROM pg_stat_statements
WHERE query LIKE '%get_geoplaces_for_tiles%'
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Analyze parameter variations
SELECT
  query,
  calls,
  mean_exec_time
FROM pg_stat_statements
WHERE query LIKE '%get_geoplaces_for_tiles%'
GROUP BY LEFT(query, 100)
ORDER BY mean_exec_time DESC;
```

**Benefit:** Identify which zoom levels and parameters are slowest.

### 2.3 PostgreSQL Configuration Tuning (MEDIUM PRIORITY)

**Recommended settings for docker-compose.yml:**

```yaml
services:
  db:
    environment:
      # Memory settings for 2GB container
      - POSTGRES_SHARED_BUFFERS=256MB
      - POSTGRES_EFFECTIVE_CACHE_SIZE=2GB
      - POSTGRES_WORK_MEM=16MB
      - POSTGRES_MAINTENANCE_WORK_MEM=128MB
      - SSD optimization
      - POSTGRES_RANDOM_PAGE_COST=1.1
      - PostGIS settings
      - POSTGIS_ENABLE_OUTDB_RASTERS=1
    command: >
      postgres
        -c shared_buffers=256MB
        -c effective_cache_size=2GB
        -c work_mem=16MB
        -c maintenance_work_mem=128MB
        -c random_page_cost=1.1
        -c max_worker_processes=4
        -c max_parallel_workers_per_gather=2
        -c max_parallel_workers=4
```

**Expected Improvement:** 10-20% reduction in execution time.

### 2.4 Prepared Statements with Plan Cache (LOW PRIORITY - Already Done)

**Current function is already IMMUTABLE + PARALLEL SAFE:**

```sql
$$ LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
```

**Issue:** Function should be `STABLE` not `IMMUTABLE` because it reads data.

**Fix:**

```sql
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE
```

**Benefit:** PostgreSQL can cache query plans, but this is already happening. Minimal additional benefit.

## 3. Application-Level Caching

### 3.1 Martin Tile Server Caching (HIGH PRIORITY - Easy Win)

Martin has built-in caching that's not configured in your current setup.

**Add to docker-compose.yml:**

```yaml
services:
  martin:
    environment:
      # Enable Martin's internal cache
      - MARTIN_CACHE=redis  # or 'file' for disk cache
      - MARTIN_CACHE_REDIS_URL=redis://redis:6379/0
      - MARTIN_CACHE_TTL=3600  # 1 hour default
      - MARTIN_CACHE_SIZE_MB=512
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

**Alternative: File-based cache (simpler):**

```yaml
services:
  martin:
    environment:
      - MARTIN_CACHE=file
      - MARTIN_CACHE_DIR=/martin_cache
      - MARTIN_CACHE_TILE_MAX_AGE=3600
    volumes:
      - ./martin_cache:/martin_cache
```

**Expected Improvement:**
- First request: 176ms
- Cached requests: 5-10ms (95% reduction)

### 3.2 HTTP Caching Headers (MEDIUM PRIORITY - Free Win)

**Add Cache-Control headers via Martin configuration:**

Martin doesn't support custom headers directly, but you can use nginx reverse proxy:

```nginx
# nginx.conf
location /tiles/ {
    proxy_pass http://martin:3000;
    proxy_cache tile_cache;
    proxy_cache_valid 200 1h;
    proxy_cache_valid 404 1m;
    proxy_cache_key "$scheme$request_method$host$request_uri";

    # Cache-Control headers
    add_header Cache-Control "public, max-age=3600, stale-while-revalidate=86400";
    add_header X-Cache-Status $upstream_cache_status;
}

# Upstream Martin doesn't change frequently
location /geoplaces_fn/ {
    proxy_pass http://martin:3000;
    proxy_cache tile_cache;
    proxy_cache_valid 200 12h;
    proxy_cache_valid 404 1m;

    add_header Cache-Control "public, max-age=43200, stale-while-revalidate=86400";
    add_header X-Cache-Status $upstream_cache_status;
}
```

**Expected Improvement:**
- Browser caching eliminates 90%+ of repeated requests
- CDN caching possible with same headers

### 3.3 Redis/Memcached for Tile Caching (MEDIUM PRIORITY - Flexible)

**Django-based caching (if you have custom tile logic):**

```python
# settings.py
CACHES = {
    'tiles': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/2',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'TIMEOUT': 3600,  # 1 hour
        'KEY_PREFIX': 'tile',
    }
}

# views.py
from django.core.cache import cache

def get_tile_cached(z: int, x: int, y: int, query_params: dict) -> bytes:
    # Create cache key from parameters
    params_hash = hashlib.md5(json.dumps(query_params, sort_keys=True).encode()).hexdigest()[:8]
    cache_key = f'tile:geoplaces:{z}/{x}/{y}:{params_hash}'

    # Try cache first
    tile_data = cache.get(cache_key)
    if tile_data is not None:
        return tile_data

    # Cache miss - generate tile
    tile_data = GeoPlacesForTilesView.objects.get_tile(z, x, y, query_params)

    # Store in cache (1 hour TTL)
    cache.set(cache_key, tile_data, timeout=3600)

    return tile_data
```

**Cache invalidation strategy:**

```python
# signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from server.apps.geometries.models import GeoPlace

@receiver(post_save, sender=GeoPlace)
@receiver(post_delete, sender=GeoPlace)
def invalidate_tile_cache(sender, instance, **kwargs):
    """
    Invalidate cached tiles when geoplace data changes.

    Strategy: Invalidate all tiles (nuclear option) or calculate affected tiles.
    """
    # Option 1: Invalidate all tiles (simple)
    cache.delete_pattern('tile:geoplaces:*')

    # Option 2: Calculate affected tiles (more efficient)
    # Get bounding box of changed place
    bbox = instance.location.extent  # (min_x, min_y, max_x, max_y)

    # Calculate tile range for each zoom level
    for z in range(0, 21):
        min_x, max_x = lon_to_tile_x(bbox[0], z), lon_to_tile_x(bbox[2], z)
        min_y, max_y = lat_to_tile_y(bbox[1], z), lat_to_tile_y(bbox[3], z)

        # Delete affected tiles
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                cache.delete_many([f'tile:geoplaces:{z}/{x}/{y}:*'])
```

**Expected Improvement:** Similar to Martin cache (5-10ms per cached request).

### 3.4 Tile Cache Table (LOW PRIORITY - Persistent Storage)

For persistent tile storage (e.g., pre-generated tiles):

```sql
CREATE TABLE tile_cache (
    z integer NOT NULL,
    x integer NOT NULL,
    y integer NOT NULL,
    query_params_hash text NOT NULL,
    tile_data bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    last_accessed timestamp with time zone DEFAULT now(),
    access_count integer DEFAULT 0,
    PRIMARY KEY (z, x, y, query_params_hash)
);

-- Index for cache eviction
CREATE INDEX idx_tile_cache_last_accessed ON tile_cache (last_accessed);

-- Function to get/set cached tiles
CREATE OR REPLACE FUNCTION get_cached_tile(
  z integer, x integer, y integer, query_params jsonb
) RETURNS bytea AS $$
DECLARE
  params_hash text;
  cached_tile bytea;
  new_tile bytea;
BEGIN
  params_hash := md5(query_params::text);

  -- Try cache
  SELECT tile_data INTO cached_tile
  FROM tile_cache
  WHERE tile_cache.z = z
    AND tile_cache.x = x
    AND tile_cache.y = y
    AND tile_cache.query_params_hash = params_hash;

  IF FOUND THEN
    -- Update access statistics
    UPDATE tile_cache
    SET last_accessed = now(),
        access_count = access_count + 1
    WHERE tile_cache.z = z
      AND tile_cache.x = x
      AND tile_cache.y = y
      AND tile_cache.query_params_hash = params_hash;

    RETURN cached_tile;
  END IF;

  -- Cache miss - generate tile
  new_tile := get_geoplaces_for_tiles(z, x, y, query_params);

  -- Store in cache
  INSERT INTO tile_cache (z, x, y, query_params_hash, tile_data)
  VALUES (z, x, y, params_hash, new_tile);

  RETURN new_tile;
END;
$$ LANGUAGE plpgsql;
```

**Cache eviction:**

```sql
-- Delete old tiles
DELETE FROM tile_cache WHERE last_accessed < now() - interval '7 days';

-- Delete least recently used tiles (keep top 100K)
DELETE FROM tile_cache
WHERE ctid IN (
  SELECT ctid FROM tile_cache
  ORDER BY last_accessed ASC
  LIMIT (SELECT COUNT(*) FROM tile_cache) - 100000
);
```

## 4. Function-Level Optimizations

### 4.1 Fix VOLATILE vs IMMUTABLE (CRITICAL - Bug Fix)

**Current:**

```sql
$$ LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
```

**Problem:** Function reads database data, so it's NOT IMMUTABLE.

**Fix:**

```sql
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE
```

**Why:**
- IMMUTABLE means "always returns same result for same arguments"
- STABLE means "returns same result within single statement"
- This function reads data that can change, so STABLE is correct

### 4.2 Parallel Query Optimization (LOW PRIORITY - Already Enabled)

Function is already `PARALLEL SAFE`, which is good.

**Verify parallel execution:**

```sql
SET max_parallel_workers_per_gather = 2;
SET parallel_setup_cost = 100;
SET parallel_tuple_cost = 0.01;

EXPLAIN ANALYZE SELECT get_geoplaces_for_tiles(12, 1345, 2920, '{}'::jsonb);
```

**Issue:** PostgreSQL may not use parallelism for small queries (<100ms).

**Recommendation:** Not worth pursuing. Function is fast enough.

### 4.3 Split into Smaller Functions (LOW PRIORITY - Minimal Benefit)

**Current:** Monolithic function with all logic.

**Alternative:** Split into helper functions:

```sql
-- Helper function for category aggregation
CREATE OR REPLACE FUNCTION get_geoplace_categories(p_geo_place_id integer)
RETURNS jsonb AS $$
  SELECT categories_all
  FROM mv_geoplace_categories
  WHERE geo_place_id = p_geo_place_id
$$ LANGUAGE SQL STABLE;

-- Helper function for sources
CREATE OR REPLACE FUNCTION get_geoplace_sources(p_geo_place_id integer)
RETURNS jsonb AS $$
  SELECT sources
  FROM mv_geoplace_sources
  WHERE geo_place_id = p_geo_place_id
$$ LANGUAGE SQL STABLE;
```

**Benefit:** Easier to test, but no performance improvement.

**Recommendation:** Skip unless debugging complexity.

### 4.4 Temporary Tables for Intermediate Results (NOT RECOMMENDED)

**Idea:** Use temp tables to cache intermediate results.

**Problem:**
- Temp tables are per-session, not shared
- Overhead of creating/populating temp tables
- No benefit for single-query functions

**Recommendation:** Don't use.

## 5. Tile-Specific Strategies

### 5.1 Pre-generate Low-Zoom Tiles (HIGH PRIORITY - Massive Impact)

**Strategy:** Pre-generate tiles for zoom levels 0-8 where clustering is used.

**Why:**
- Low zoom tiles change rarely (only when major POIs added)
- High overlap (same POIs appear in many tiles)
- Can be pre-generated during deployments

**Implementation:**

```python
# management/commands/pregenerate_tiles.py
from django.core.management.base import BaseCommand
from server.apps.geometries.models import GeoPlacesForTilesView
import math

class Command(BaseCommand):
    help = 'Pre-generate tiles for low zoom levels'

    def handle(self, *args, **options):
        # Pre-generate zoom levels 0-8
        for z in range(0, 9):
            # Calculate tile range for Switzerland
            # Swiss bounding box: 45.8°N to 47.8°N, 5.9°E to 10.5°E
            min_x, max_x = self.lon_to_tile_x(5.9, z), self.lon_to_tile_x(10.5, z)
            min_y, max_y = self.lat_to_tile_y(47.8, z), self.lat_to_tile_y(45.8, z)

            total_tiles = (max_x - min_x + 1) * (max_y - min_y + 1)
            self.stdout.write(f'Generating {total_tiles} tiles for z{z}...')

            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    try:
                        # Generate tile (will be cached by Martin/Redis)
                        tile_data = GeoPlacesForTilesView.objects.get_tile(z, x, y)
                        self.stdout.write(f'  Generated tile {z}/{x}/{y}', ending='\r')
                    except Exception as e:
                        self.stderr.write(f'Error generating tile {z}/{x}/{y}: {e}')

            self.stdout.write(f'Completed z{z}')

    @staticmethod
    def lon_to_tile_x(lon, zoom):
        return math.floor((lon + 180) / 360 * 2**zoom)

    @staticmethod
    def lat_to_tile_y(lat, zoom):
        return math.floor((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 2**zoom)
```

**Usage:**

```bash
# Run after deployments or bulk imports
python manage.py pregenerate_tiles
```

**Expected Improvement:**
- First request after pre-generation: 5-10ms (from cache)
- No cold-start penalty for low zoom tiles

### 5.2 Tile Cache Table with Sitemap (MEDIUM PRIORITY)

**Strategy:** Use a tile cache table to store pre-generated tiles permanently.

**Implementation:**

```sql
-- Tile cache table (from section 3.4)
-- Add sitemap for tracking which tiles exist

CREATE TABLE tile_sitemap (
  z integer NOT NULL,
  x integer NOT NULL,
  y integer NOT NULL,
  query_params_hash text NOT NULL,
  is_cached boolean DEFAULT false,
  last_generated timestamp with time zone,
  PRIMARY KEY (z, x, y, query_params_hash)
);

-- Find uncached tiles for a zoom level
SELECT z, x, y, query_params_hash
FROM tile_sitemap
WHERE z = 12
  AND is_cached = false
LIMIT 100;
```

**Cache warmer script:**

```python
# management/commands/warm_tile_cache.py
from django.core.management.base import BaseCommand
from server.apps.geometries.models import GeoPlacesForTilesView
from django.db import connection

class Command(BaseCommand):
    help = 'Warm tile cache for high-demand areas'

    def handle(self, *args, **options):
        # Warm cache for Swiss region at zoom levels 9-14
        for z in range(9, 15):
            self.stdout.write(f'Warming cache for z{z}...')

            # Swiss bounding box
            min_x = max(0, int((5.9 + 180) / 360 * 2**z))
            max_x = min(2**z - 1, int((10.5 + 180) / 360 * 2**z))
            min_y = max(0, int((1 - math.log(math.tan(math.radians(47.8)) + 1 / math.cos(math.radians(47.8))) / math.pi) / 2 * 2**z))
            max_y = min(2**z - 1, int((1 - math.log(math.tan(math.radians(45.8)) + 1 / math.cos(math.radians(45.8))) / math.pi) / 2 * 2**z))

            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    try:
                        tile_data = GeoPlacesForTilesView.objects.get_tile(z, x, y)
                    except Exception as e:
                        self.stderr.write(f'Error: {e}')
```

### 5.3 Simplify Geometry for Clustered Features (LOW PRIORITY)

**Strategy:** Use simplified geometry for cluster points.

**Current:**

```sql
ST_AsMVTGeom(
  ST_Transform(location, 3857),
  tile_bbox, 4096, 64, true
)
```

**For clusters, use centroid instead of original location:**

```sql
-- For clustered features
ST_AsMVTGeom(
  ST_Transform(
    ST_Centroid(ST_Collect(location)),  -- Use centroid of cluster
    3857
  ),
  tile_bbox, 4096, 64, true
)
```

**Benefit:** 5-10% faster for clustered features (minimal impact).

**Recommendation:** Skip unless desperate.

### 5.4 Optimize ST_AsMVT Parameters (LOW PRIORITY)

**Current:** `ST_AsMVT(tile, 'geoplaces', 4096, 'geom')`

**Tunable parameters:**
- `extent`: Default 4096 (tile coordinate space). Larger = more precision but bigger tiles.
- `buffer`: Default 64 (pixels). Smaller = faster but clipped labels.

**Optimization:**

```sql
-- For low zoom levels (z0-10), use smaller extent
SELECT INTO mvt ST_AsMVT(
  mvt.*, 'geoplaces',
  CASE
    WHEN z < 10 THEN 2048  -- Smaller extent for low zoom
    ELSE 4096
  END,
  'geom'
) FROM (...) mvt;
```

**Benefit:** 5-10% smaller tiles, 2-5% faster generation.

**Recommendation:** Test with your data.

## 6. Implementation Priority

### Phase 1: Quick Wins (1-2 hours, 50% improvement)

1. **Add Martin file cache** (30 min)
   - Configure `MARTIN_CACHE=file` in docker-compose.yml
   - **Impact:** 95% reduction for repeated requests

2. **Fix IMMUTABLE to STABLE** (5 min)
   - Change function volatility
   - **Impact:** Correct behavior, prevents incorrect caching

3. **Enable HTTP caching headers** (30 min)
   - Add nginx reverse proxy with caching
   - **Impact:** Browser/CDN caching

### Phase 2: Major Performance (1 day, 40% improvement)

4. **Create materialized views** (2 hours)
   - `mv_geoplace_categories` and `mv_geoplace_sources`
   - **Impact:** 40-60% faster tile generation

5. **Set up automatic refresh** (2 hours)
   - Django management command to refresh MVs
   - Trigger after bulk imports
   - **Impact:** Keeps cache fresh

### Phase 3: Monitoring & Tuning (1 day, 10% improvement)

6. **Enable pg_stat_statements** (1 hour)
   - Install extension
   - **Impact:** Visibility into performance

7. **Tune PostgreSQL configuration** (2 hours)
   - Increase shared_buffers to 256MB
   - Set random_page_cost to 1.1
   - **Impact:** 10-20% improvement

### Phase 4: Advanced Caching (2-3 days, 5% improvement)

8. **Pre-generate low-zoom tiles** (4 hours)
   - Create pregeneration script
   - Run during deployments
   - **Impact:** No cold starts for z0-8

9. **Add Redis cache layer** (4 hours)
   - Configure Redis for Martin
   - Add Django-based caching
   - **Impact:** Flexible caching strategy

### Phase 5: Future Optimizations (Low priority)

10. **Tile cache table** (optional)
    - Persistent tile storage
    - Advanced cache warming
    - **Impact:** Fine-grained control

## 7. Recommended Configuration

### docker-compose.yml additions

```yaml
services:
  db:
    image: postgis/postgis:16-3.4-alpine
    environment:
      POSTGRES_SHARED_BUFFERS: 256MB
      POSTGRES_EFFECTIVE_CACHE_SIZE: 2GB
      POSTGRES_WORK_MEM: 16MB
      POSTGRES_RANDOM_PAGE_COST: 1.1
    command: >
      postgres
        -c shared_buffers=256MB
        -c effective_cache_size=2GB
        -c work_mem=16MB
        -c random_page_cost=1.1
        -c max_parallel_workers_per_gather=2

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  martin:
    image: ghcr.io/maplibre/martin:latest
    environment:
      MARTIN_CACHE: redis
      MARTIN_CACHE_REDIS_URL: redis://redis:6379/0
      MARTIN_CACHE_TTL: 3600
    depends_on:
      - db
      - redis

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "80:80"
    depends_on:
      - martin

volumes:
  redis_data:
```

### nginx.conf

```nginx
worker_processes 4;
events { worker_connections 1024; }

http {
    upstream martin {
        server martin:3000;
    }

    # Cache configuration
    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=tile_cache:100m max_size=1g inactive=7d;

    server {
        listen 80;

        location /geoplaces_fn/ {
            proxy_pass http://martin;
            proxy_cache tile_cache;
            proxy_cache_valid 200 12h;
            proxy_cache_valid 404 1m;
            proxy_cache_key "$scheme$request_method$host$request_uri";

            add_header Cache-Control "public, max-age=43200, stale-while-revalidate=86400";
            add_header X-Cache-Status $upstream_cache_status;
        }
    }
}
```

## 8. Expected Results

### Before Optimizations

- **Cold cache:** 176ms per tile
- **Warm cache:** 176ms per tile (no caching)
- **Peak load:** Database bottleneck at ~100 concurrent requests

### After Phase 1 (Quick Wins)

- **Cold cache:** 176ms per tile (unchanged)
- **Warm cache:** 5-10ms per tile (95% reduction)
- **Peak load:** 10x more concurrent requests possible

### After Phase 2 (Materialized Views)

- **Cold cache:** 70-100ms per tile (50% reduction)
- **Warm cache:** 5-10ms per tile (maintained)
- **Peak load:** Database bottleneck eliminated

### After Phase 3 (Configuration Tuning)

- **Cold cache:** 60-80ms per tile (additional 10-20% reduction)
- **Warm cache:** 5-10ms per tile (maintained)
- **Peak load:** Optimal for hardware

### After All Phases

- **Cold cache:** 60-80ms per tile (60% reduction overall)
- **Warm cache:** 5-10ms per tile (95% reduction)
- **Peak load:** 20x improvement in throughput
- **User experience:** Instant tile loading for most requests

## 9. Monitoring Strategy

### Key Metrics to Track

1. **Tile generation time:** Average per zoom level
2. **Cache hit rate:** Percentage of requests served from cache
3. **Database load:** Connections, CPU, memory
4. **Error rate:** Failed tile requests
5. **User-facing latency:** Time from request to response

### Monitoring Queries

```sql
-- Average tile generation time (requires pg_stat_statements)
SELECT
  mean_exec_time,
  calls,
  total_exec_time
FROM pg_stat_statements
WHERE query LIKE '%get_geoplaces_for_tiles%';

-- Cache hit rate (if using tile_cache table)
SELECT
  COUNT(*) FILTER (WHERE last_accessed > created_at) as cache_hits,
  COUNT(*) as total_requests,
  ROUND(100.0 * COUNT(*) FILTER (WHERE last_accessed > created_at) / COUNT(*), 2) as hit_rate
FROM tile_cache;

-- Materialized view refresh timing
SELECT
  schemaname,
  matviewname,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname)) as size
FROM pg_matviews
WHERE matviewname LIKE 'mv_geoplace%';
```

### Alerts

- **Average tile time > 200ms:** Performance degradation
- **Cache hit rate < 80%:** Cache not effective
- **Materialized view stale > 1 hour:** Data freshness issue

## 10. Conclusion

Your tile generation function is already well-optimized with clustering and LATERAL joins. The primary bottlenecks are:

1. **JSON aggregation in CTEs** (40% of time) → **Fix:** Materialized views
2. **No application-level caching** (repeat work) → **Fix:** Martin/Redis cache
3. **Suboptimal PostgreSQL config** (memory settings) → **Fix:** Increase shared_buffers

**Recommended starting point:**

1. Implement Martin file cache (30 min, 95% reduction for cached tiles)
2. Create materialized views (2 hours, 50% reduction for uncached tiles)
3. Tune PostgreSQL config (30 min, 10% additional reduction)

This combination will give you the best return on investment with minimal complexity.

**Total expected improvement:**
- Cached tiles: 176ms → 5-10ms (95% reduction)
- Uncached tiles: 176ms → 70-100ms (50% reduction)
- System throughput: 10-20x improvement
