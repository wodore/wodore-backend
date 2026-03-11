from django.db import migrations


def create_geoplaces_tile_function(forwards_sql):
    return """
    -- Function: get_geoplaces_for_tiles(z, x, y, query_params)
    -- Purpose: Generate dynamic vector tiles for geoplaces with advanced filtering
    --
    -- This function is called by Martin tile server to generate vector tiles on-demand.
    -- It supports dynamic filtering via query parameters to optimize tile size and content.
    --
    -- Parameters:
    --   z (integer): Zoom level (0-20)
    --   x (integer): Tile X coordinate
    --   y (integer): Tile Y coordinate
    --   query_params (jsonb): Query parameters for filtering (see docs below)
    --
    -- Query Parameters (optional):
    --   lang (text): Language code for names (de, en, fr, it) - default: null (uses Django LANGUAGE_CODE)
    --   categories (text): Comma-separated category slugs (OR logic) - default: null (all)
    --                     Example: "hut,hotel,parking"
    --   categories_all (text): Comma-separated category slugs (AND logic) - default: null (all)
    --                          Example: "hut,parking" (places with BOTH hut AND parking)
    --   fields (text): Comma-separated field names to include - default: null (all)
    --                  Example: "slug,name,importance,categories"
    --                  Available fields: slug, name, importance, detail_type, elevation,
    --                                    country_code, categories, extra, sources
    --   min_importance (integer): Override auto importance filter - default: null (auto by zoom)
    --   max_features (integer): Max features per tile - default: null (no limit)
    --                          When set, orders by importance DESC, then RANDOM()
    --                          This ensures important places are shown first,
    --                          and remaining places are spatially distributed
    --
    -- Returns:
    --   bytea: MVT (Mapbox Vector Tile) encoded tile data
    --
    -- Usage Examples via Martin URLs:
    --   /geoplaces_fn/{z}/{x}/{y}                                         # Uses Django default language
    --   /geoplaces_fn/{z}/{x}/{y}?lang=en                                 # English labels
    --   /geoplaces_fn/{z}/{x}/{y}?categories=hut,hotel                    # Only huts and hotels
    --   /geoplaces_fn/{z}/{x}/{y}?categories_all=hut,parking              # Huts with parking
    --   /geoplaces_fn/{z}/{x}/{y}?fields=slug,name,importance             # Minimal fields
    --   /geoplaces_fn/{z}/{x}/{y}?lang=en&categories=hut&fields=slug,name,elevation
    --
    -- Usage Examples via SQL:
    --   SELECT get_geoplaces_for_tiles(12, 1234, 2345, '{"lang": "en"}');
    --   SELECT get_geoplaces_for_tiles(10, 500, 400, '{"categories": "hut,hotel", "max_features": 5000}');
    --
    -- Note: When lang parameter is NULL (default), Django's LANGUAGE_CODE setting is used.
    --       See: server/settings/components/common.py for LANGUAGE_CODE configuration
    --
    -- See: server/apps/geometries/models/tiles_view.py for full documentation

    CREATE OR REPLACE FUNCTION get_geoplaces_for_tiles(
      z integer,
      x integer,
      y integer,
      query_params jsonb DEFAULT '{}'::jsonb
    )
    RETURNS bytea AS $$
    DECLARE
      mvt bytea;
      requested_language text;
      categories_filter text;
      categories_all_filter text;
      fields_filter text;
      min_importance_override integer;
      max_features_limit integer;
      min_importance integer;
      tile_envelope geometry;
      categories_array text[];
      categories_all_array text[];
      fields_array text[];
    BEGIN
      -- Extract query parameters with defaults
      -- For NULL lang, we'll use 'de' as fallback (Django default is typically 'de')
      -- Martin can't access Django settings, so this is a reasonable default
      requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
      categories_filter := query_params->>'categories';
      categories_all_filter := query_params->>'categories_all';
      fields_filter := query_params->>'fields';
      min_importance_override := (query_params->>'min_importance')::integer;
      max_features_limit := (query_params->>'max_features')::integer;

      -- Convert comma-separated strings to arrays
      categories_array := NULLIF(categories_filter, '')::text[];
      categories_all_array := NULLIF(categories_all_filter, '')::text[];
      fields_array := NULLIF(fields_filter, '')::text[];

      -- If arrays are empty, treat as NULL (no filtering)
      IF categories_array = ARRAY[]::text[] THEN
        categories_array := NULL;
      END IF;
      IF categories_all_array = ARRAY[]::text[] THEN
        categories_all_array := NULL;
      END IF;
      IF fields_array = ARRAY[]::text[] THEN
        fields_array := NULL;
      END IF;

      -- Calculate minimum importance based on zoom level (can be overridden)
      -- Relaxed thresholds with max_features limit and RANDOM() ordering
      min_importance := COALESCE(
        min_importance_override,
        CASE z
          WHEN 0 THEN 90  -- Country/continental level: only major cities
          WHEN 1 THEN 90
          WHEN 2 THEN 90
          WHEN 3 THEN 80
          WHEN 4 THEN 80
          WHEN 5 THEN 60
          WHEN 6 THEN 60  -- National level (e.g., Switzerland)
          WHEN 7 THEN 25  -- Swiss level (2x Switzerland): show everything over 25
          WHEN 8 THEN 15  -- Swiss level continued
          WHEN 9 THEN 1   -- Canton level: show everything except 0
          WHEN 10 THEN 1  -- Canton level continued
          WHEN 11 THEN 1
          WHEN 12 THEN 0  -- Village level: show everything including 0
          WHEN 13 THEN 0
          WHEN 14 THEN 0
          WHEN 15 THEN 0
          ELSE 0  -- Zoom 16+: show all places
        END
      );

      -- Get tile envelope for intersection test
      tile_envelope := ST_Transform(ST_TileEnvelope(z, x, y), 4326);

      -- Generate MVT tile with dynamic property selection
      WITH filtered_places AS (
        SELECT
          gp.slug,
          gp.location,
          gp.importance,
          gp.detail_type,
          gp.elevation,
          gp.country_code,
          gp.extra,

          -- Dynamic name based on requested language
          CASE requested_language
            WHEN 'de' THEN COALESCE(gp.i18n->>'name_de', gp.name, '')
            WHEN 'en' THEN COALESCE(gp.i18n->>'name_en', gp.name, '')
            WHEN 'fr' THEN COALESCE(gp.i18n->>'name_fr', gp.name, '')
            WHEN 'it' THEN COALESCE(gp.i18n->>'name_it', gp.name, '')
            ELSE COALESCE(gp.name, '')
          END as name,

          -- Categories (always included, used for filtering)
          COALESCE(
            (
              SELECT jsonb_agg(
                jsonb_build_object(
                  'slug', cat.slug,
                  'identifier', cat.identifier,
                  'order', cat."order",
                  'color', cat.color,
                  'parent_slug', parent.slug
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

          -- Sources (always included, can be filtered later)
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
        WHERE gp.is_public = true
          AND gp.is_active = true
          AND gp.importance >= min_importance
          AND gp.location && tile_envelope

          -- Category filtering (OR logic): places in ANY of these categories
          AND (
            categories_array IS NULL
            OR gp.id IN (
              SELECT gpc.geo_place_id
              FROM geometries_geoplace_category gpc
              JOIN categories_category cat ON gpc.category_id = cat.id
              WHERE cat.slug = ANY(categories_array)
            )
          )

          -- Category filtering (AND logic): places in ALL of these categories
          AND (
            categories_all_array IS NULL
            OR gp.id IN (
              SELECT gpc.geo_place_id
              FROM geometries_geoplace_category gpc
              JOIN categories_category cat ON gpc.category_id = cat.id
              WHERE cat.slug = ANY(categories_all_array)
              GROUP BY gpc.geo_place_id
              HAVING COUNT(DISTINCT cat.slug) = array_length(categories_all_array, 1)
            )
          )

        -- Order by importance first (highest priority), then random for spatial distribution
        -- When max_features is set, this ensures:
        -- 1. Most important places are included first
        -- 2. Remaining slots are filled with random places (spatially distributed)
        ORDER BY gp.importance DESC, RANDOM()

        -- Limit features if specified
        LIMIT COALESCE(max_features_limit, NULL)::bigint
      )
      SELECT INTO mvt ST_AsMVT(tile, 'geoplaces', 4096, 'geom') FROM (
        SELECT
          ST_AsMVTGeom(
            ST_Transform(fp.location, 3857),
            ST_TileEnvelope(z, x, y),
            4096, 64, true
          ) AS geom,

          -- Fields: use defaults if fields_array IS NULL, otherwise use requested fields
          -- Default fields: slug, name, importance, categories, sources
          CASE
            WHEN fields_array IS NULL OR 'slug' = ANY(fields_array)
            THEN fp.slug
            ELSE NULL::text
          END as slug,

          CASE
            WHEN fields_array IS NULL OR 'name' = ANY(fields_array)
            THEN fp.name
            ELSE NULL::text
          END as name,

          CASE
            WHEN fields_array IS NULL OR 'importance' = ANY(fields_array)
            THEN fp.importance
            ELSE NULL::integer
          END as importance,

          -- Optional fields (only if explicitly requested)
          CASE
            WHEN fields_array IS NOT NULL AND 'detail_type' = ANY(fields_array)
            THEN fp.detail_type
            ELSE NULL::text
          END as detail_type,

          CASE
            WHEN fields_array IS NOT NULL AND 'elevation' = ANY(fields_array)
            THEN fp.elevation
            ELSE NULL::integer
          END as elevation,

          CASE
            WHEN fields_array IS NOT NULL AND 'country_code' = ANY(fields_array)
            THEN fp.country_code
            ELSE NULL::text
          END as country_code,

          -- Categories and sources (included in defaults)
          CASE
            WHEN fields_array IS NULL OR 'categories' = ANY(fields_array)
            THEN fp.categories
            ELSE NULL::jsonb
          END as categories,

          -- Extra (optional, not in defaults)
          CASE
            WHEN fields_array IS NOT NULL AND 'extra' = ANY(fields_array)
            THEN fp.extra
            ELSE NULL::jsonb
          END as extra,

          CASE
            WHEN fields_array IS NULL OR 'sources' = ANY(fields_array)
            THEN fp.sources
            ELSE NULL::jsonb
          END as sources

        FROM filtered_places fp
        WHERE fp.location && tile_envelope
      ) as tile WHERE geom IS NOT NULL;

      RETURN mvt;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE;


    -- Add function comment with TileJSON metadata
    -- This metadata will be merged into Martin's auto-generated TileJSON
    COMMENT ON FUNCTION get_geoplaces_for_tiles IS $$
    {
      "description": "GeoPlaces vector tiles with dynamic filtering by language, categories, fields, and importance",
      "minzoom": 0,
      "maxzoom": 20,
      "attribution": "© Wodore",
      "vector_layers": [
        {
          "id": "geoplaces",
          "description": "Points of interest with dynamic properties based on query parameters",
          "fields": {
            "slug": "String",
            "name": "String",
            "importance": "Number",
            "detail_type": "String",
            "elevation": "Number",
            "country_code": "String",
            "categories": "Array",
            "extra": "Object",
            "sources": "Array"
          }
        }
      ]
    }
    $$;

    -- Grant permissions (adjust as needed for your setup)
    GRANT EXECUTE ON FUNCTION get_geoplaces_for_tiles(integer, integer, integer, jsonb) TO PUBLIC;
    """


def remove_geoplaces_tile_function(reverse_sql):
    return """
    DROP FUNCTION IF EXISTS get_geoplaces_for_tiles(integer, integer, integer, jsonb) CASCADE;
    """


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0027_create_geoplaces_tiles_view"),
    ]

    operations = [
        migrations.RunSQL(
            sql=create_geoplaces_tile_function(forwards_sql=None),
            reverse_sql=remove_geoplaces_tile_function(reverse_sql=None),
        ),
    ]
