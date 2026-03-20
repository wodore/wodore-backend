---
draft: false
date:
  created: 2026-03-16
  updated: 2026-03-16
slug: wep009
categories:
  - WEP
  - UX
tags:
  - wep009
  - postgis
  - martin
---

# `WEP 9` POI Clustering for Vector Tiles

POIs are served as vector tiles via a Martin Postgres function. At low zoom levels many POIs overlap, making the map unreadable. This spec defines a category-aware, importance-weighted clustering strategy that:

- Groups POIs into grid cells per category using `ST_SnapToGrid`
- Represents each cell with the highest-importance POI (location + icon)
- Lets high-importance POIs graduate to raw mode at a lower zoom than low-importance ones
- Accepts an optional fixed radius in metres to override the default zoom-derived grid size
- Returns a consistent MVT feature schema at all zoom levels

## MVT Feature Schema

All features — clustered or raw — return the same property set. This keeps MapLibre expressions simple and avoids conditional `has()` checks.

| Property    | Type    | Clustered  | Notes                                                          |
|-------------|---------|------------|----------------------------------------------------------------|
| `category`  | string  | value      | Category identifier (e.g., "tourism.hut", "finance.atm")        |
| `icon`      | string  | value      | Icon identifier (category slug for MapLibre sprite lookup)      |
| `importance`| integer | value      | Importance score of the representative POI (0–100)             |
| `count`     | integer | value      | Number of POIs in cell. Always `1` for raw tiles               |
| `name`      | string  | `''`       | Name of representative POI. Empty string when clustered        |
| `slug`      | string  | `''`       | URL slug of representative POI. Empty string when clustered    |

Cluster detection in MapLibre: `['>', ['get', 'count'], 1]`

## Multi-Category POI Handling

**Important**: A single POI can belong to multiple categories (e.g., a "hut" that also has "parking"). The clustering strategy handles this as follows:

1. **Flattening**: POI-category relationships are flattened via `geometries_geoplace_category` junction table
2. **Multiple appearances**: A POI with 3 categories appears 3 times in the data (once per category)
3. **Independent clustering**: Each appearance is clustered independently within its category group
4. **Result**: A single POI can be represented in multiple cluster cells (one per category)

**Example**: A mountain hut with parking at zoom 8:

- Appears in the "tourism.hut" cluster cell (with other huts)
- Also appears in the "parking" cluster cell (with other parking)
- When zoomed in (z13+), both raw features are rendered separately

**Frontend consideration**: The same POI may appear multiple times in a tile at different locations (clustered by category). This is intentional and correct behavior for category-aware clustering.

## Martin Function Parameters

```sql
poi_clustered_tiles(
  z                         int,
  x                         int,
  y                         int,
  lang                      text  DEFAULT 'de',
  cluster_max_zoom          int   DEFAULT 8,
  cluster_low_zoom_offset   int   DEFAULT 4,
  importance_threshold      int   DEFAULT 50,
  cluster_radius_m          float DEFAULT NULL,
  cluster_ref_zoom          int   DEFAULT 8
)
```

| Parameter                | Type / Default  | Unit    | Description                                                                                                      |
|--------------------------|-----------------|---------|------------------------------------------------------------------------------------------------------------------|
| `lang`                   | text / `'de'`   | -       | Language code for multilingual names (de, en, fr, it)                                                            |
| `cluster_max_zoom`       | int / `8`       | zoom    | High-importance POIs switch to raw above this zoom. z=8 ≈ full Switzerland view. `NULL` disables clustering.     |
| `cluster_low_zoom_offset`| int / `2`       | zoom    | Low-importance POIs stay clustered this many extra zoom levels beyond `cluster_max_zoom`.                        |
| `importance_threshold`   | int / `50`      | 0–100   | POIs with `importance >= threshold` are high-priority and graduate to raw at `cluster_max_zoom`.                 |
| `cluster_radius_m`       | float / `NULL`  | metres  | Cluster radius at `cluster_ref_zoom`. Scaled per zoom level. `NULL` = use default pixel-based grid size.         |
| `cluster_ref_zoom`       | int / `8`       | zoom    | The zoom at which `cluster_radius_m` applies. z=8 ≈ full Switzerland view.                                      |

### Grid size resolution

Each zoom level halves the tile size in metres, so the grid size scales accordingly:

```
grid_size(z) = cluster_radius_m × 2^(ref_zoom − z)
```

Example with `cluster_radius_m=5000` at `cluster_ref_zoom=8`:

| Zoom | Grid size |
|------|-----------|
| 6    | 20 000 m  |
| 7    | 10 000 m  |
| 8    |  5 000 m  ← anchor |
| 9    |  2 500 m  |
| 10   |  1 250 m  |

```sql
grid_size := COALESCE(
  cluster_radius_m * power(2.0, cluster_ref_zoom - z),
  40075016.0 / (256.0 * power(2, z))  -- fallback: one cell per tile pixel
);
```

This is mathematically equivalent to the pixel-derived formula — just expressed in a geographically intuitive way. When `cluster_radius_m` is `NULL` the pixel formula is used and `cluster_ref_zoom` is ignored.

## Zoom-Level Behaviour

| Zoom range                                              | Behaviour                                                  |
|---------------------------------------------------------|------------------------------------------------------------|
| `z <= cluster_max_zoom`                                 | All POIs clustered by (category, grid cell)                |
| `cluster_max_zoom < z <= cluster_max_zoom + offset`     | High-importance POIs raw. Low-importance still clustered.  |
| `z > cluster_max_zoom + cluster_low_zoom_offset`        | All POIs raw. No clustering.                               |
| `cluster_max_zoom = NULL`                               | No clustering at any zoom level.                           |

### Default example

With `cluster_max_zoom=8`, `offset=2`, `threshold=50`:

- **z ≤ 8** — everything clustered
- **z 9–10** — SAC huts, named shelters (importance ≥ 50) shown individually; unknown shelters still clustered
- **z ≥ 11** — all POIs raw

## Clustering Logic

### Grid size

Grid cell size is computed in EPSG:3857 (metres). When `cluster_radius_m` is provided it is anchored at `cluster_ref_zoom` and scaled per zoom level; otherwise one cell per tile pixel is used:

```sql
grid_size := COALESCE(
  cluster_radius_m * power(2.0, cluster_ref_zoom - z),
  40075016.0 / (256.0 * power(2, z))
);
```

`ST_SnapToGrid` is applied after `ST_Transform(geom, 3857)` so snapping is in metres regardless of the source CRS.

### Representative POI

Within each `(category, grid cell)` group, the POI with the highest importance is chosen as representative. Its **original geometry** is used — not the snapped grid centre. A single POI in a cell therefore keeps its exact original coordinates.

```sql
(array_agg(geom        ORDER BY importance DESC))[1]  -- location
(array_agg(icon        ORDER BY importance DESC))[1]  -- icon
(array_agg(importance  ORDER BY importance DESC))[1]  -- importance score
(array_agg(name        ORDER BY importance DESC))[1]  -- name (raw only)
(array_agg(slug        ORDER BY importance DESC))[1]  -- slug (raw only)
```

### Feature Limit Application

**Important**: The `max_features` limit is applied **AFTER** clustering, only to the raw features branch.

This means:

1. **Clustering runs first**: All POIs are grouped into clusters (if clustering is enabled)
2. **Raw features extracted**: High-importance and above-cutoff POIs are extracted as raw features
3. **Feature limit applied**: The raw features are then limited by `max_features` (if specified)
4. **Results combined**: Clustered features (unlimited) + raw features (limited) are returned

**Example**: With `max_features=100` at zoom 10:

- 500 low-importance POIs → 50 cluster features (no limit applied)
- 150 high-importance POIs → limited to 100 raw features
- Total tile: 150 features (50 clusters + 100 raw POIs)

This approach ensures:

- Clusters are never artificially limited (maintaining spatial distribution)
- Raw features are capped to prevent oversized tiles
- High-importance POIs are prioritized within the limit (ordered by importance DESC)

### UNION structure

The function uses `UNION ALL` of two branches:

**Cluster branch** — POIs below the importance threshold that are still within the clustering zoom range. Groups by `(category, ST_SnapToGrid(...))`. Returns `count`, empty `name` and `slug`.

**Raw branch** — high-importance POIs above `cluster_max_zoom`, and all POIs above the full cutoff (`cluster_max_zoom + offset`). Returns `count=1`, populated `name` and `slug`.

### Full SQL

```sql
CREATE OR REPLACE FUNCTION poi_clustered_tiles(
  z                        int,
  x                        int,
  y                        int,
  cluster_max_zoom         int   DEFAULT 8,
  cluster_low_zoom_offset  int   DEFAULT 4,
  importance_threshold     int   DEFAULT 50,
  cluster_radius_m         float DEFAULT NULL,
  cluster_ref_zoom         int   DEFAULT 8
)
RETURNS bytea AS $$
DECLARE
  tile_bbox  geometry;
  grid_size  float;
  result     bytea;
BEGIN
  tile_bbox := ST_TileEnvelope(z, x, y);

  grid_size := COALESCE(
    cluster_radius_m * power(2.0, cluster_ref_zoom - z),
    40075016.0 / (256.0 * power(2, z))
  );

  SELECT ST_AsMVT(mvt.*, 'pois', 4096, 'geom')
  INTO result
  FROM (

    -- Cluster branch: low-importance POIs still within clustering range
    SELECT
      ST_AsMVTGeom(
        (array_agg(geom       ORDER BY importance DESC))[1],
        tile_bbox, 4096, 64, true
      )                                                        AS geom,
      category,
      (array_agg(icon        ORDER BY importance DESC))[1]    AS icon,
      (array_agg(importance  ORDER BY importance DESC))[1]    AS importance,
      COUNT(*)::int                                            AS count,
      ''::text                                                 AS name,
      ''::text                                                 AS slug
    FROM poi
    WHERE geom && tile_bbox
      AND ST_Intersects(geom, tile_bbox)
      AND (
        cluster_max_zoom IS NOT NULL
        AND z <= cluster_max_zoom + cluster_low_zoom_offset
        AND importance < importance_threshold
      )
    GROUP BY
      category,
      ST_SnapToGrid(ST_Transform(geom, 3857), grid_size)

    UNION ALL

    -- Raw branch: high-importance POIs above base cutoff, and all POIs above full cutoff
    SELECT
      ST_AsMVTGeom(geom, tile_bbox, 4096, 64, true)           AS geom,
      category,
      icon,
      importance,
      1                                                        AS count,
      name,
      slug
    FROM poi
    WHERE geom && tile_bbox
      AND ST_Intersects(geom, tile_bbox)
      AND (
        cluster_max_zoom IS NULL
        OR z > cluster_max_zoom + cluster_low_zoom_offset
        OR (importance >= importance_threshold AND z > cluster_max_zoom)
      )
    ORDER BY importance DESC
    LIMIT 500

  ) mvt
  WHERE geom IS NOT NULL;

  RETURN result;
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;
```

## Implementation Details

### Database Schema

The function uses the existing Wodore schema:

- **`geometries_geoplace`**: Core POI data (location, importance, i18n names)
- **`geometries_geoplace_category`**: Junction table for POI-category relationships
- **`categories_category`**: Category definitions with identifiers (e.g., "tourism.hut")

### Icon Mapping

Icons are derived from the category `slug` field:

- Category slug `"hut"` → icon identifier `"hut"`
- Frontend maps icon IDs to MapLibre sprites: `"icon-" + category_slug`
- Example: `"hut"` → sprite `"icon-hut"`, `"atm"` → sprite `"icon-atm"`

**Note**: The Category model has `symbol_detailed`, `symbol_simple`, and `symbol_mono` fields (foreign keys to Image model), but for vector tile performance, we use the simple `slug` as the icon identifier. The frontend can load appropriate sprites based on zoom level and style.

### Performance Indexes

Recommended indexes for optimal clustering query performance:

```sql
-- Covering index for clustering queries
CREATE INDEX idx_geoplace_clustered
  ON geometries_geoplace (importance, location)
  WHERE is_public = true AND is_active = true;

-- Index for category lookups (already exists)
-- CREATE INDEX idx_geoplace_category ON geometries_geoplace_category (geo_place_id, category_id);

-- Partial index for high-importance places (low zoom tiles)
CREATE INDEX idx_geoplace_high_importance
  ON geometries_geoplace (location, importance)
  WHERE is_public = true AND is_active = true AND importance >= 80;
```

### Migration

The function is created in migration `0029_poi_clustered_tiles.py` with:

- Forward SQL: Creates `poi_clustered_tiles()` function
- Reverse SQL: Drops function with CASCADE
- Dependencies: Requires `0028_create_geoplaces_tile_function`

## MapLibre Integration

### Source

```js
map.addSource('pois', {
  type: 'vector',
  tiles: [
    `https://tiles.wodore.com/poi_clustered_tiles/{z}/{x}/{y}`
    + `?cluster_max_zoom=8`
  ],
  minzoom: 0,
  maxzoom: 16,
});
```

Pass optional overrides as query params: `?cluster_max_zoom=10&cluster_radius_m=5000`

### Layer per category

One symbol layer per category. Icon comes directly from the `icon` property.

```js
for (const cat of categories) {
  map.addLayer({
    id: `poi-${cat}`,
    type: 'symbol',
    source: 'pois',
    'source-layer': 'pois',
    filter: ['==', ['get', 'category'], cat],
    layout: {
      'icon-image': ['get', 'icon'],
      // Slightly larger when representing multiple POIs
      'icon-size': ['interpolate', ['linear'], ['get', 'count'],
        1, 1.0,  // single POI — normal size
        5, 1.3,  // 5+ POIs — capped at 1.3×
      ],
      'icon-allow-overlap': false,
    },
  });
}
```

### Zoom crossfade

Smooth opacity transition across the clustering cutoff:

```js
// Clustered layer — fades out
'icon-opacity': ['interpolate', ['linear'], ['zoom'],
  cluster_max_zoom - 0.5, 1,
  cluster_max_zoom + 0.5, 0,
],
'icon-opacity-transition': { duration: 400 },

// Raw layer — fades in
'icon-opacity': ['interpolate', ['linear'], ['zoom'],
  cluster_max_zoom - 0.5, 0,
  cluster_max_zoom + 0.5, 1,
],
'icon-opacity-transition': { duration: 400 },
```

## Implementation Notes

- **ST_SnapToGrid operates in EPSG:3857.** `ST_Transform` is applied before snapping; output geometry is in tile CRS via `ST_AsMVTGeom`.
- **`cluster_radius_m` scales with zoom.** The radius is anchored at `cluster_ref_zoom` and halved per zoom level inward, so clustering density remains visually consistent as you zoom. When `NULL` the pixel-derived formula is used and `cluster_ref_zoom` is ignored.
- **Single POI keeps original position.** The representative POI's real geometry is used, not the grid centre. A lone POI in a cell is never snapped.
- **`STABLE PARALLEL SAFE`** allows Postgres to use parallel workers on large tiles.
- **Martin >= 0.13** required for query parameters to be forwarded as named function arguments.
- **Collision at intermediate zooms.** A high-importance raw POI and a low-importance cluster representative may land near the same pixel. `icon-allow-overlap: false` lets MapLibre's collision detection resolve this.
- **`count=1` on raw tiles** means no special-casing is needed in MapLibre — the `icon-size` interpolation handles single vs cluster naturally.
