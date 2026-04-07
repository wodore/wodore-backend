"""
PostgreSQL view and function for Martin vector tiles.

This module provides:
1. GeoPlacesForTilesView - A PostgreSQL view for basic tile serving
2. get_geoplaces_for_tiles() - A dynamic function for advanced tile serving

## Function-Based Tile Serving (Recommended)

The `get_geoplaces_for_tiles()` function provides dynamic tile generation with:
- Category-aware clustering at low zoom levels (configurable thresholds)
- Language selection (reduces tile size by only returning requested language)
- Field filtering (only include requested properties)
- Importance-based zoom filtering (automatic or manual override)
- Max feature limiting (prevent oversized tiles)
- Database-level tile caching with TTL and cache versioning

### Function Location
Latest migration: server/apps/geometries/migrations/0041_optimize_tile_performance.py

### Query Parameters
```json
{
  "lang": "en",                           // Language code (de, en, fr, it) - default: "de"
  "cluster_max_zoom": 6,                  // Max zoom for clustering - default: 6
  "cluster_low_zoom_offset": 2,           // Extra zooms for transition - default: 2
  "importance_threshold": 50,             // Importance for early raw graduation - default: 50
  "cluster_radius_m": 5000.0,             // Cluster radius in meters at ref zoom - default: auto
  "cluster_ref_zoom": 8,                  // Reference zoom for cluster_radius_m - default: 8
  "max_features": 10000,                  // Max features per tile - default: null (no limit)
  "max_label_zoom": 14,                   // Only include name above this zoom - default: 14
  "fields": "category,color,importance,count,name,slug",  // Fields to include - default: see list
  "cache_ttl_days": 7,                    // Cache TTL in days - default: 7
  "cache_version": 1                      // Bump to invalidate all cached tiles - default: 1
}
```

### Clustering Behavior (defaults)
- **z <= cluster_max_zoom**: All POIs clustered by (category, grid_cell). Cluster radius scales with zoom.
- **cluster_max_zoom < z <= max+offset**: Transition zone. High-importance POIs (>= threshold) shown raw, low-importance still clustered with shrinking grid.
- **z > max+offset**: All POIs raw (no clustering).

### Caching Behavior
- Tiles cached in `geometries_tile_cache` table
- Cache key: md5(query_params + cache_version)
- Cache invalidated by `expires_at` TTL or by bumping `cache_version`
- Cached tiles skipped entirely on cache hit (no SQL query generation)

### Architecture
The function uses two separate query paths for performance:
- **Clustered path** (low zoom): Minimal fields, no categories/sources JSON aggregation.
  Pre-computes location in EPSG:3857 once. Uses `COUNT(*)` instead of `COUNT(DISTINCT)`.
- **Raw path** (high zoom): Full fields with optional categories/sources aggregation.

### Usage Examples via Martin
```
# All defaults (German, clustering enabled, 7-day cache)
GET /geoplaces/{z}/{x}/{y}

# English labels only
GET /geoplaces/{z}/{x}/{y}?lang=en

# Extend clustering to z10
GET /geoplaces/{z}/{x}/{y}?cluster_max_zoom=10

# Disable clustering (all raw)
GET /geoplaces/{z}/{x}/{y}?cluster_max_zoom=null

# Larger clusters (10km at z8)
GET /geoplaces/{z}/{x}/{y}?cluster_radius_m=10000

# Bypass cache (fresh tiles)
GET /geoplaces/{z}/{x}/{y}?cache_ttl_days=0

# Invalidate all cached tiles
GET /geoplaces/{z}/{x}/{y}?cache_version=2
```

### Django Manager Usage
```python
from server.apps.geometries.models import GeoPlacesForTilesView

# Get tile with Django default language
tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345)

# Get tile with specific language
tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345, {"lang": "en"})

# Get tile with clustering disabled
tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345, {"cluster_max_zoom": "null"})
```

### Changelog
- 2025-03-11: Initial implementation with language, fields, categories, and importance filtering (migration `0028`)
- 2025-03-xx: Category-aware clustering with grid-based grouping, importance graduation (migration `0032`)
- 2025-03-xx: Database-level tile caching with TTL and hit counting (migration `0036`)
- 2025-03-xx: Inline caching in main function, cache_version and expires_at support (migration `0037`)
- 2025-04-05: Performance optimization — partial GIST index, faster bbox filter, eliminated RANDOM(), scoped CTEs (migration `0038`)
- 2025-04-05: Fix cluster grid_size transition zone logic, default cluster_max_zoom 8→6 (migration `0040`)
- 2025-04-06: Major performance pass (migration `0041_optimize_tile_performance`):
  - Split into clustered/raw query paths (skip JSON aggregation for clustered zooms)
  - Remove ORDER BY md5() + LIMIT from sampled_pois
  - Pre-compute location_3857 once (eliminate repeated ST_Transform)
  - Replace EXECUTE format() cache INSERT with static SQL
  - COUNT(*) instead of COUNT(DISTINCT slug) for clusters
  - MATERIALIZED CTE hint on sampled_pois
  - martin.yaml: buffer 64→16, maxzoom 20/24→16 for all point layers
"""

from django.conf import settings
from django.contrib.gis.db import models
from django.db import connection
from psqlextra.models import PostgresViewModel


class GeoPlacesForTilesViewManager(models.Manager):
    """
    Manager for GeoPlacesForTilesView with helper methods for tile generation.
    """

    def get_tile(self, z: int, x: int, y: int, query_params: dict = None) -> bytes:
        """
        Get vector tile for given coordinates.

        This method calls the get_geoplaces_for_tiles PostgreSQL function
        and automatically applies the Django default language if not specified.

        Args:
            z: Zoom level (0-20)
            x: Tile X coordinate
            y: Tile Y coordinate
            query_params: Optional dict of query parameters (lang, categories, fields, etc.)
                         Example: {"lang": "en", "categories": "hut,hotel"}

        Returns:
            MVT tile data as bytes

        Example:
            # Get tile with Django defaults
            tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345)

            # Get tile with English labels
            tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345, {"lang": "en"})

            # Get tile with filters
            tile = GeoPlacesForTilesView.objects.get_tile(
                12, 1234, 2345,
                {"lang": "en", "categories": "hut", "fields": "slug,name"}
            )
        """
        if query_params is None:
            query_params = {}

        # Apply Django default language if not specified
        if "lang" not in query_params:
            query_params["lang"] = settings.LANGUAGE_CODE

        # Convert dict to JSON for PostgreSQL
        import json

        query_params_json = json.dumps(query_params)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT get_geoplaces_for_tiles(%s, %s, %s, %s::jsonb)",
                [z, x, y, query_params_json],
            )
            result = cursor.fetchone()
            return result[0] if result else None


class GeoPlacesForTilesView(PostgresViewModel):
    """
    PostgreSQL view for Martin vector tile server.

    Provides geoplaces data with:
    - Multilingual names (de, en, fr, it) with fallbacks via modeltrans
    - Multiple categories with parent information and extra data
    - Detail type (amenity, transport, natural, admin, none)
    - Extra field for category-specific overflow data
    - Organization sources
    - Country code and importance
    - Elevation data

    Only includes public and active places (is_public=true AND is_active=true).

    Note: Using SQL instead of QuerySet because PostgresViewModel compiles
    the query at import time, before Django apps are ready. This means we
    cannot use ORM features that require model access.
    """

    # Core fields
    slug = models.CharField(max_length=200, primary_key=True)
    location = models.PointField(srid=4326)

    # Elevation and location
    elevation = models.IntegerField(null=True, blank=True)
    country_code = models.CharField(max_length=2)
    importance = models.SmallIntegerField()

    # Default language name with fallbacks (based on MODELTRANS_FALLBACK)
    name = models.CharField(max_length=200)

    # Multilingual names (dynamically generated based on LANGUAGES setting)
    # These will be populated with fallbacks via MODELTRANS_FALLBACK
    name_de = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    name_fr = models.CharField(max_length=200)
    name_it = models.CharField(max_length=200)

    # Categories (JSON array with all categories)
    # Each category has: slug, identifier, order, color, parent_slug, extra
    categories = models.JSONField(default=list)

    # Detail type
    detail_type = models.CharField(max_length=50)

    # Extra data (category-specific overflow)
    extra = models.JSONField(default=dict)

    # Organization sources (array of objects with slug and source_id)
    sources = models.JSONField(default=list)

    class Meta:
        managed = False
        db_table = "geoplaces_for_tiles"

    # Custom manager with helper methods
    objects = GeoPlacesForTilesViewManager()

    class ViewMeta:
        """
        ViewMeta configuration for django-postgres-extra.

        The 'query' attribute can be SQL string or (SQL, params) tuple.
        Using SQL allows the view to be created at migration time.
        """

        @staticmethod
        def query():
            """
            Generate SQL for creating the view.

            Uses COALESCE for multilingual fallbacks based on MODELTRANS_FALLBACK setting.
            Matches the same pattern used in HutsForTilesView for consistency.

            Returns (SQL, params) tuple.
            """
            # Get fallback configuration
            fallback_config = getattr(settings, "MODELTRANS_FALLBACK", {})
            language_code = settings.LANGUAGE_CODE  # 'de'
            languages = getattr(settings, "LANGUAGE_CODES", ["de", "en", "fr", "it"])

            # Build COALESCE statements for each language with fallbacks
            name_selects = []
            for lang in languages:
                # Get fallback chain for this language
                fallbacks = fallback_config.get(lang, [language_code])
                fallback_chain = [lang] + [fb for fb in fallbacks if fb != lang]

                # Build COALESCE expression
                coalesce_parts = []
                for fallback_lang in fallback_chain:
                    if fallback_lang == language_code:
                        # Default language is in 'name' field
                        coalesce_parts.append("gp.name")
                    else:
                        # Other languages in i18n JSONB field
                        coalesce_parts.append(f"gp.i18n->>'name_{fallback_lang}'")

                # Add final fallback to name if not already included
                if "gp.name" not in coalesce_parts:
                    coalesce_parts.append("gp.name")

                coalesce_expr = f"COALESCE({', '.join(coalesce_parts)}) as name_{lang}"
                name_selects.append(coalesce_expr)

            name_columns = ",\n      ".join(name_selects)

            # Build the name field for default language (must duplicate the expression, can't use alias)
            # Get the COALESCE expression for the default language
            default_lang_coalesce = None
            for i, lang in enumerate(languages):
                if lang == language_code:
                    # This is the expression we need to duplicate
                    default_fallbacks = fallback_config.get(lang, [language_code])
                    fallback_chain = [lang] + [
                        fb for fb in default_fallbacks if fb != lang
                    ]

                    coalesce_parts = []
                    for fallback_lang in fallback_chain:
                        if fallback_lang == language_code:
                            coalesce_parts.append("gp.name")
                        else:
                            coalesce_parts.append(f"gp.i18n->>'name_{fallback_lang}'")

                    if "gp.name" not in coalesce_parts:
                        coalesce_parts.append("gp.name")

                    default_lang_coalesce = f"COALESCE({', '.join(coalesce_parts)})"
                    break

            sql = f"""
            SELECT DISTINCT ON (gp.id)
              gp.slug,
              gp.location,
              gp.elevation,
              gp.country_code,
              gp.importance,
              gp.detail_type,
              gp.extra,

              -- Default language name with fallbacks (based on MODELTRANS_FALLBACK)
              {default_lang_coalesce} as name,

              -- Multilingual names with fallbacks (based on MODELTRANS_FALLBACK)
              {name_columns},

              -- Categories (JSON array with all categories for this place)
              -- Each category has: slug, identifier, order, color, parent_slug, parent_name, extra
              COALESCE(
                (
                  SELECT jsonb_agg(
                    jsonb_build_object(
                      'slug', cat.slug,
                      'identifier', cat.identifier,
                      'order', cat."order",
                      'color', cat.color,
                      'parent_slug', parent.slug,
                      'parent_name', parent.name,
                      'extra', gpc.extra
                    )
                    ORDER BY cat."order"
                  )
                  FROM geometries_geoplace_category gpc
                  LEFT JOIN categories_category cat ON gpc.category_id = cat.id
                  LEFT JOIN categories_category parent ON cat.parent_id = parent.id
                  WHERE gpc.geo_place_id = gp.id AND cat.id IS NOT NULL
                ),
                '[]'::jsonb
              ) as categories,

              -- Organization sources (slug and source_id)
              -- Matches the pattern used in HutsForTilesView
              COALESCE(
                (
                  SELECT jsonb_agg(
                    jsonb_build_object(
                      'slug', o.slug,
                      'source_id', gsa.source_id
                    )
                  )
                  FROM geometries_geoplacesourceassociation gsa
                  LEFT JOIN organizations_organization o ON gsa.organization_id = o.id
                  WHERE gsa.geo_place_id = gp.id AND o.slug IS NOT NULL
                ),
                '[]'::jsonb
              ) as sources

            FROM geometries_geoplace gp
            WHERE gp.is_public = true AND gp.is_active = true
            """

            # Return tuple of (SQL, params) - no params needed for this query
            return (sql.strip(), [])
