
# Image Aggregation – Design & Plugin System

## Overview

A lightweight aggregation layer that queries multiple image sources in parallel
for a given coordinate + radius, normalises results into a unified schema, and
returns them with full source and license metadata.

Each source is implemented as an independent **provider plugin**. Adding a new
source means writing one class — no changes to the core aggregation logic.

---

## Unified Image Schema

Every provider must return images conforming to this shape:

```json
{
  "source": "wikidata",
  "source_id": "Q12345",
  "source_url": "https://www.wikidata.org/wiki/Q12345",

  "image_type": "flat",
  "captured_at": "2022-08-14T10:30:00Z",

  "location": { "lat": 46.912, "lon": 8.541 },
  "distance_m": 34,

  "license": {
    "slug": "cc-by-sa-4.0",
    "name": "CC BY-SA 4.0",
    "url": "https://creativecommons.org/licenses/by-sa/4.0/"
  },
  "attribution": "Author Name, CC BY-SA 4.0",

  "urls": {
    "original":             "https://...",
    "avatar":               "https://img.wodore.com/...",
    "thumb":                "https://img.wodore.com/...",
    "preview":              "https://img.wodore.com/...",
    "preview_placeholder":  "https://img.wodore.com/...",
    "medium":               "https://img.wodore.com/...",
    "large":                "https://img.wodore.com/..."
  }
}
```

### Field notes

| Field | Notes |
|---|---|
| `source` | Identifier of the provider (see list below) |
| `source_id` | Original ID in the source system |
| `source_url` | Deep link back to the source |
| `image_type` | `flat` or `360` — affects how the frontend renders it |
| `captured_at` | When the photo was taken, not when it was indexed |
| `distance_m` | Distance from query coordinate, computed server-side |
| `license.slug` | Normalised slug: `cc0`, `cc-by`, `cc-by-sa-4.0`, `copyright`, `unknown` |
| `attribution` | Ready-to-render HTML attribution string |
| `urls.original` | Raw unproxied source URL, used for attribution links |
| `urls.*` | All other sizes proxied through `img.wodore.com` for caching |

---

## Provider Interface

Every provider implements the same interface:

```python
class ImageProvider:
    source: str          # e.g. "wikidata"
    cache_ttl: int       # seconds — how long results are cached

    async def fetch(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        qid: str | None = None,   # optional hint for providers that support direct lookup
    ) -> list[ImageResult]:
        """
        Query the source for images near the given coordinate.
        Must return a list of ImageResult objects (or empty list).
        Must never raise — catch and log errors internally.

        qid: Wikidata QID (e.g. "Q12345") — providers that support direct
             entity lookup (Wikidata) use this to skip geospatial queries
             when available. Ignored by providers that don't support it.
        """
        raise NotImplementedError
```

Key constraints:

- **Never raises** — a failing provider returns `[]`, it never breaks the aggregation
- **Always async** — providers use `httpx.AsyncClient` for external HTTP
- **Self-contained** — all source-specific logic (auth, pagination, URL building) lives inside the provider
- **Own TTL** — each provider declares its own cache TTL since sources update at different rates

---

## Aggregation Flow

```
Request (lat, lon, radius)
        │
        ├── own DB provider      → instant, no cache needed
        │
        ├── check cache per provider
        │       ├── FRESH (<1h)         → return cached
        │       ├── STALE (1h–30d)      → return cached + refresh in background
        │       └── EXPIRED (>30d)      → refresh live, then return
        │
        └── asyncio.gather(all providers)
                │
                └── merge + sort by distance → unified response
```

Background refresh uses a simple thread (no Celery needed) — the stale result
is returned immediately while the refresh runs behind the scenes.

### Cache key

```
images:{source}:{lat_rounded}:{lon_rounded}:{radius_km}
```

Coordinates are rounded to 4 decimal places (~11m grid) by default. Per-source
caching means Wikidata and Panoramax refresh independently.

For hut-centric queries the coordinate always comes from the DB and is always
identical, so rounding has no practical effect — cache hits are near 100%.
Rounding matters for free-form map queries where nearby taps should share a
cache entry.

Precision is configurable via an optional `precision` parameter:

| Level | Decimal places | Grid approx. | Use case |
|---|---|---|---|
| `broad` | 2 | ~1100m | City / area queries |
| `normal` | 3 | ~111m | Neighbourhood queries |
| `precise` | 4 | ~11m | Hut / POI queries (default) |
| `exact` | — | no rounding | Raw coordinate passthrough |

### Cache backend

Django's built-in `DatabaseCache` backed by PostgreSQL. Run
`python manage.py createcachetable` once. No Redis required.

---

## Provider Catalogue

### ✅ Own DB

- **Source:** Wodore PostgreSQL / PostGIS
- **Query:** Spatial radius query on your own image table
- **License:** As stored per image
- **Cache TTL:** None — always live
- **Notes:** Highest priority, always returned first

---

### ✅ Wikidata / Wikimedia Commons

- **Source:** `www.wikidata.org` REST API or `query.wikidata.org` SPARQL endpoint
- **License:** Typically CC-BY-SA, stored per file on Commons
- **Cache TTL:** 7 days (changes very rarely)
- **Query strategy — QID takes priority:**

  ```
  hut.wikidata_qid present?
      YES → REST API: GET /wiki/Special:EntityData/{QID}.json
            parse claims.P18 → image filename(s)
            fast, no SPARQL overhead
      NO  → SPARQL: wikibase:around + P625 (coordinate) + P18 (image)
            radius-based fallback for huts without a known QID
  ```

  Image filenames from both paths resolve to CDN URLs via
  `https://commons.wikimedia.org/wiki/Special:FilePath/{filename}`.

- **Notes:** Best source for canonical, high-quality hut photos. The QID path
  is significantly faster (~100ms vs ~500ms for SPARQL) and should be used
  whenever the hut model has a `wikidata` field — which most SAC/DAV huts in
  OSM do. The SPARQL fallback ensures coverage for huts not yet linked to Wikidata.

---

### ✅ Panoramax

- **Source:** Any STAC-compliant Panoramax instance
- **Query:** `GET /api/search?bbox=...` or `intersects` with GeoJSON
- **License:** CC-BY-SA (OSM France instance)
- **Cache TTL:** 6 hours
- **Notes:** Best for trail approach photos and sequences. Can query
  `api.panoramax.xyz` (meta-catalog) or a self-hosted instance. Filter by
  `collections` parameter to restrict to specific instances.

---

### Mapillary

- **Source:** `graph.mapillary.com` (Meta)
- **Query:** Images API with `bbox` + `fields`
- **License:** CC-BY-SA (images), proprietary platform
- **Cache TTL:** 12 hours
- **Notes:** Largest street-level coverage globally. Requires API key.
  Useful where Panoramax coverage is thin (e.g. remote Alpine areas).
  Meta ownership is the main concern.

---

### Flickr

- **Source:** `api.flickr.com`
- **Query:** `flickr.photos.search` with `lat/lon/radius` + `license` filter
- **License:** Filter to CC-BY (`license=1`) and CC-BY-SA (`license=2`) only
- **Cache TTL:** 24 hours
- **Notes:** Large volume of Alpine photos. Quality varies. Worth filtering to
  `accuracy=16` (street level) or higher to avoid noise. Good gap-filler for
  huts with no other coverage.

---

## Deduplication

The same physical image can appear from multiple providers — a Wikidata P18
image is also on Wikimedia Commons, or the same contributor uploaded a sequence
to both Panoramax and Mapillary. Deduplication runs after merging all provider
results, before returning the response.

Two levels are applied in order:

### Level 1 — Exact match (cheap, always run)

**Commons filename normalisation** catches Wikidata ↔ Commons overlap. Any
URL referencing Wikimedia Commons can be reduced to its canonical filename,
which is globally unique on Commons:

```
https://upload.wikimedia.org/.../Foo_hut.jpg        →  "Foo_hut.jpg"
https://commons.wikimedia.org/wiki/File:Foo_hut.jpg →  "Foo_hut.jpg"
Special:FilePath/Foo_hut.jpg                        →  "Foo_hut.jpg"
```

If two results normalise to the same filename, keep the one from the higher
priority source (own DB > Wikidata > Panoramax > Mapillary > Flickr).

**`(source, source_id)` uniqueness** — within a single provider, the same
item must never appear twice. Deduplicate on this pair after each provider
returns its results.

### Level 2 — Fuzzy match (cross-platform duplicates)

Catches the same photo uploaded to both Panoramax and Mapillary by the same
contributor. Two images are considered duplicates if:

- coordinates are within **5m** of each other, AND
- `captured_at` timestamps are within **10 seconds** of each other

When a fuzzy duplicate is detected, keep the result from the higher-priority
source and discard the other. If `captured_at` is missing from either result,
skip fuzzy matching for that pair — don't guess.

### Perceptual hashing (not recommended for now)

Computing a perceptual hash (pHash) requires downloading the image, which
conflicts with the lazy proxy-caching approach. Only worth revisiting if
Level 1 + Level 2 prove insufficient in practice.

---

## Adding a New Provider

1. Create a class implementing `ImageProvider`
2. Implement `fetch()` — return `list[ImageResult]`, never raise
3. Set `source` (unique string) and `cache_ttl`
4. Register it in the provider list

That's it. The aggregation layer, caching, parallel execution, and response
merging require no changes.

---

## Streaming (optional)

For progressive loading, the API can expose an SSE endpoint that emits results
per provider as they arrive rather than waiting for all sources:

```
GET /api/images/stream?lat=46.9&lon=8.5&radius=2
```

```
data: {"source": "own",       "images": [...]}   ← instant
data: {"source": "panoramax", "images": [...]}   ← ~300ms
data: {"source": "wikidata",  "images": [...]}   ← ~500ms
data: {"source": "mapillary", "images": [...]}   ← ~400ms
data: [DONE]
```

The Quasar frontend renders images as each event arrives. Own DB results appear
immediately; external sources fill in progressively. This gives excellent
perceived performance without changing the underlying provider architecture.
