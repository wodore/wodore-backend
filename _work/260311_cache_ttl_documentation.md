# Cache TTL Documentation

**Date**: 2026-03-11
**Purpose**: Complete reference for all cache TTL values in the GeoImages API

---

## Summary

The caching system uses **3 layers** with different TTL strategies:

1. **Browser/CDN Cache** (HTTP headers) - 5 minutes
2. **Django Default Cache** (in-memory) - 5 minutes
3. **Django Persistent Cache** (database) - Provider-specific (6 hours to 7 days)

---

## 1. Browser/CDN Cache (HTTP Cache-Control)

### Implementation
```python
@decorate_view(cache_control(max_age=300))  # 5 minutes
```

### TTL: **5 minutes (300 seconds)**

**Endpoints**:
- ✅ `/v1/geo/images/nearby` - 5 minutes
- ✅ `/v1/geo/images/place/{slug}` - 5 minutes
- ✅ `/v1/geo/images/hut/{slug}` - 5 minutes

**What this does**:
- Sets HTTP header: `Cache-Control: max-age=300`
- Browser caches response for 5 minutes
- CDN (if used) caches for 5 minutes
- After 5 minutes, browser revalidates with server

**Other GeoPlace endpoints** (shorter TTL):
- `/v1/geo/search` - **1 minute (60 seconds)**
- `/v1/geo/nearby` - **1 minute (60 seconds)**
- `/v1/geo/amenities/{id}` - **1 minute (60 seconds)**

**Why shorter for GeoPlaces?**
- GeoPlace data changes more frequently than images
- Faster propagation of updates
- Still provides significant caching benefit

---

## 2. Django Default Cache (In-Memory)

### Configuration
**Location**: `server/settings/components/caches.py`

```python
"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "TIMEOUT": 300,  # 5 minutes default
    "OPTIONS": {
        "MAX_ENTRIES": 1000,
    }
}
```

### TTL: **5 minutes (300 seconds)**

**Used for**:
- Frequently changing data
- Session data (if configured)
- Temporary computations
- django-axes rate limiting

**Limitations**:
- ❌ Not shared between workers (multi-process)
- ❌ Lost on server restart
- ❌ Limited to 1000 entries

**Production recommendation**:
```python
# Use Redis instead
"default": {
    "BACKEND": "django_redis.cache.RedisCache",
    "LOCATION": "redis://127.0.0.1:6379/0",
    "TIMEOUT": 300,
}
```

---

## 3. Django Persistent Cache (Database)

### Configuration
**Location**: `server/settings/components/caches.py`

```python
"persistent": {
    "BACKEND": "django.core.cache.backends.db.DatabaseCache",
    "LOCATION": "django_cache_persistent",
    "TIMEOUT": None,  # Indefinite (overridden by individual cache keys)
    "OPTIONS": {
        "MAX_ENTRIES": 10000,
        "CULL_FREQUENCY": 4,
    }
}
```

### Base TTL: **Indefinite (None)**
**Individual cache keys set their own TTL**

**Used for**:
- ✅ Provider image results (long-term)
- ✅ Provider metadata (indefinite)
- ✅ License information (indefinite)

**Advantages**:
- ✅ Persists across server restarts
- ✅ Shared between workers
- ✅ Can hold 10,000 entries
- ✅ Transactional (database-backed)

---

## Provider Cache TTLs

### Image Provider Caching

Each provider has its own TTL based on how often their data changes:

| Provider | TTL | Rationale |
|----------|-----|-----------|
| **Wodore** | 0 (no cache) | Always live - queries database directly |
| **Panoramax** | 6 hours | User-generated content, updates frequently |
| **Mapillary** | 12 hours | Moderate update frequency |
| **Camptocamp** | 24 hours | Community updates daily |
| **Flickr** | 24 hours | Stable image metadata |
| **Wikidata** | 7 days | Rarely changes, highly stable |
| **Wikimedia Commons** | 24 hours | Stable image metadata |

### Implementation Details

```python
# server/apps/geometries/providers/panoramax.py
class PanoramaxProvider(ImageProvider):
    source = "panoramax"
    cache_ttl = 6 * 60 * 60  # 6 hours
    priority = 3

# server/apps/geometries/providers/wikidata.py
class WikidataProvider(ImageProvider):
    source = "wikidata"
    cache_ttl = 7 * 24 * 60 * 60  # 7 days
    priority = 2
```

### Cache Key Format

```
geoimages:{provider}:images:{lat}:{lon}:{radius}:{precision}
```

**Examples**:
- `geoimages:panoramax:images:46.631:8.343:50:precise`
- `geoimages:camptocamp:images:46.631:8.343:50:precise`
- `geoimages:wikimedia_commons:images:46.631:8.343:50:precise`

---

## Metadata Caching

### Provider Information

**Cache key**: `geoimages:provider:{provider_name}`
**TTL**: **1 year (indefinite)**

```python
# server/apps/geometries/providers/base.py
def _get_provider_info(provider_name: str) -> dict:
    cache = get_persistent_cache()
    cache_key = f"{CACHE_KEY_PREFIX}:provider:{provider_name}"
    # ...
    cache.set(cache_key, provider_info, CACHE_INDEFINITE)  # 1 year
```

**Rationale**: Provider metadata (name, URL, description) rarely changes.

### License Information

**Cache key**: `geoimages:license:{slug}`
**TTL**: **1 year (indefinite)**

```python
# server/apps/geometries/providers/base.py
def _get_license_info(slug: str) -> dict:
    cache = get_persistent_cache()
    cache_key = f"{CACHE_KEY_PREFIX}:license:{slug}"
    # ...
    cache.set(cache_key, license_info, CACHE_INDEFINITE)  # 1 year
```

**Rationale**: License terms are stable and rarely change.

---

## Cache Hierarchy (Request Flow)

When a user requests `/v1/geo/images/hut/gelmer`:

```
1. Browser Cache (HTTP Cache-Control)
   ├─ Hit? → Return immediately (0ms)
   └─ Miss? → Continue to server

2. Django Default Cache (LocMemCache)
   ├─ Hit? → Return cached data (~1-5ms)
   └─ Miss? → Continue to persistent cache

3. Django Persistent Cache (Database)
   ├─ Provider Cache Hit? → Return cached data (~50-100ms)
   │  ├─ Wodore: Always live (query DB)
   │  ├─ Panoramax: 6h TTL
   │  ├─ Camptocamp: 24h TTL
   │  └─ Wikimedia: 24h TTL
   └─ All Providers Miss?
      → Fetch from external APIs (~500-1000ms)
      → Store in persistent cache
      → Return to client
```

---

## Performance Impact

### Current Performance (with caching)

| Cache Level | Response Time | Speedup |
|-------------|---------------|---------|
| **Browser cache hit** | ~5-10ms | 99% faster |
| **Provider cache hit** | ~50-100ms | 92% faster |
| **All caches miss** | ~500-1000ms | baseline |

### Example: Gelmerhütte

```
Request 1 (cold start):
- Browser miss → Provider miss → Fetch APIs
- Time: ~600-1000ms

Request 2 (provider cached):
- Browser miss → Provider hit → Return cached
- Time: ~50-100ms

Request 3-12 (browser cached):
- Browser hit → Return immediately
- Time: ~5-10ms
```

---

## Cache Invalidation

### Manual Invalidation

#### Specific Location
```python
from server.apps.geometries.providers import PanoramaxProvider

provider = PanoramaxProvider()
provider.invalidate_cache(lat=46.631, lon=8.343, radius=50)
```

#### Entire Provider
```python
from server.apps.geometries.providers.base import ImageProvider

ImageProvider.invalidate_all_provider_cache("panoramax")
```

### Management Command

```bash
# Show cache statistics
app image_cache stats --provider=all

# Invalidate specific location
app image_cache invalidate --provider=camptocamp --lat=46.631 --lon=8.343 --radius=50

# Warm cache for a hut
app image_cache warm --hunt=gelmer

# Clear all cache
app image_cache clear-all --provider=all
```

---

## Recommendations

### Current Setup ✅

**Good**:
- ✅ Appropriate TTLs for each provider
- ✅ Browser caching reduces server load
- ✅ Persistent cache survives restarts
- ✅ Manual invalidation available

**Could be improved**:
- ⚠️ LocMemCache doesn't work with multi-worker (gunicorn)
- ⚠️ No ETag support for conditional requests
- ⚠️ No cache hit/miss metrics

### Production Recommendations

#### 1. Use Redis for Default Cache

**Before** (LocMemCache):
```python
"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "TIMEOUT": 300,
}
```

**After** (Redis):
```python
"default": {
    "BACKEND": "django_redis.cache.RedisCache",
    "LOCATION": "redis://127.0.0.1:6379/0",
    "TIMEOUT": 300,
    "OPTIONS": {
        "CLIENT_CLASS": "django_redis.client.DefaultClient",
    }
}
```

**Benefits**:
- ✅ Shared between workers
- ✅ Persists across restarts
- ✅ Better performance
- ✅ Supports cache metrics

#### 2. Add ETag Support

```python
from django.utils.http import quote_etag
import hashlib
import json

def generate_etag(data: dict) -> str:
    content = json.dumps(data, sort_keys=True)
    hash_value = hashlib.sha256(content.encode()).hexdigest()
    return quote_etag(hash_value)

# In endpoint
etag = generate_etag(response_data.model_dump())
if request.headers.get('If-None-Match') == etag:
    return HttpResponse(status=304)
```

**Benefits**:
- ✅ Save bandwidth (304 responses)
- ✅ Better cache validation
- ✅ Lower CDN costs

#### 3. Adjust Browser Cache TTL

Consider longer TTL for image endpoints:
```python
# Current: 5 minutes
@decorate_view(cache_control(max_age=300))

# Recommended: 1 hour (images change rarely)
@decorate_view(cache_control(max_age=3600))
```

**Benefits**:
- ✅ Fewer requests to server
- ✅ Better user experience
- ✅ Lower server load

---

## Quick Reference

| Cache Type | TTL | Location | Purpose |
|------------|-----|----------|---------|
| **Browser (HTTP)** | 5 min | Client side | Reduce server requests |
| **Django Default** | 5 min | In-memory (LocMem) | Temporary data |
| **Django Persistent** | Variable | Database | Long-term data |
| **Provider Images** | 6h-7d | Database | External API results |
| **Provider Metadata** | 1 year | Database | Rarely-changing info |
| **License Info** | 1 year | Database | Stable data |

---

## Monitoring

### Check Cache Hit Rate

```python
from django.core.cache import caches
from django.db import connection

cache = caches["persistent"]

with connection.cursor() as cursor:
    # Count total vs cached requests
    cursor.execute("""
        SELECT
            COUNT(*) as total_requests,
            SUM(CASE WHEN cache_key LIKE 'geoimages:%' THEN 1 ELSE 0 END) as cached_requests
        FROM django_cache_persistent
    """)
```

### Log Analysis

Look for these log patterns:
```
✅ Cache HIT  → Good! Using cached data
❌ Cache MISS → Expected on first request
🔄 UPDATE_CACHE → Forced refresh
```

---

## Summary

### Current Configuration
- **Browser cache**: 5 minutes (HTTP)
- **Django default**: 5 minutes (in-memory)
- **Django persistent**: Indefinite (database)
- **Provider caches**: 6 hours to 7 days (database)

### Performance
- **First request**: ~600-1000ms (cache miss)
- **Cached requests**: ~50-100ms (92% faster)
- **Browser cached**: ~5-10ms (99% faster)

### Next Steps
1. ✅ Provider caching implemented
2. ⏳ Add Redis for production
3. ⏳ Implement ETag support
4. ⏳ Add cache monitoring
5. ⏳ Consider longer browser cache TTL
