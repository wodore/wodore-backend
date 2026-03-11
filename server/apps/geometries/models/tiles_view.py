"""
PostgreSQL view and function for Martin vector tiles.

This module provides:
1. GeoPlacesForTilesView - A PostgreSQL view for basic tile serving
2. get_geoplaces_for_tiles() - A dynamic function for advanced tile serving

## Function-Based Tile Serving (Recommended)

The `get_geoplaces_for_tiles()` function provides dynamic tile generation with:
- Language selection (reduces tile size by only returning requested language)
- Field filtering (only include requested properties)
- Category filtering (OR/AND logic for overlays)
- Importance-based zoom filtering (automatic or manual override)
- Max feature limiting (prevent oversized tiles)

### Function Location
Migration: server/apps/geometries/migrations/0028_create_geoplaces_tile_function.py

### Query Parameters
```json
{
  "lang": "en",                       // Language code (de, en, fr, it) - default: Django LANGUAGE_CODE
  "categories": "hut,hotel",           // OR: places in ANY of these categories (comma-separated)
  "categories_all": "hut,parking"      // AND: places in ALL of these categories (comma-separated)
  "fields": "name,categories,extra",   // Which fields to include (comma-separated) - default: all
  "min_importance": 50,                // Override auto importance filter - default: null (auto by zoom)
  "max_features": 10000                // Max features per tile - default: null (no limit)
}
```

**Note:** The `lang` parameter defaults to Django's `LANGUAGE_CODE` setting (configured in
`server/settings/components/common.py`). If not specified, tiles use the default language.

### Usage Examples via Martin
```
# Uses Django default language (currently "de" in settings)
GET /geoplaces_fn/{z}/{x}/{y}

# English labels only (reduces tile size)
GET /geoplaces_fn/{z}/{x}/{y}?lang=en

# Only huts and hotels
GET /geoplaces_fn/{z}/{x}/{y}?categories=hut,hotel

# Places that are BOTH huts AND have parking
GET /geoplaces_fn/{z}/{x}/{y}?categories_all=hut,parking

# Minimal fields only (reduces tile size significantly)
GET /geoplaces_fn/{z}/{x}/{y}?fields=slug,name,importance

# Combined filters: English, huts only, minimal fields
GET /geoplaces_fn/{z}/{x}/{y}?lang=en&categories=hut&fields=slug,name,elevation
```

### Django Manager Usage
```python
from server.apps.geometries.models import GeoPlacesForTilesView

# Get tile with Django default language
tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345)

# Get tile with specific language
tile = GeoPlacesForTilesView.objects.get_tile(12, 1234, 2345, {"lang": "en"})

# Get tile with filters
tile = GeoPlacesForTilesView.objects.get_tile(
    12, 1234, 2345,
    {"lang": "en", "categories": "hut", "fields": "slug,name"}
)
```

### Changelog
- 2025-03-11: Initial implementation with language, fields, categories, and importance filtering
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
