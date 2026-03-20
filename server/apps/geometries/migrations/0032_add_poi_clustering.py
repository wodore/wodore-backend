from django.db import migrations


def update_geoplaces_tile_function_with_clustering(forwards_sql):
    return """
    -- Update function: get_geoplaces_for_tiles(z, x, y, query_params)
    -- Purpose: Generate clustered vector tiles for POIs with category-aware clustering
    --
    -- This function replaces the previous implementation with WEP009 clustering:
    -- - Category-aware clustering: POIs grouped by (category, grid_cell)
    -- - Multi-category POIs: Appear in multiple cluster groups (one per category)
    -- - Importance-weighted: High-importance POIs graduate to raw mode earlier
    -- - Zoom-dependent clustering: Automatic clustering at low zoom levels
    --
    -- Parameters:
    --   z (integer): Zoom level (0-20)
    --   x (integer): Tile X coordinate
    --   y (integer): Tile Y coordinate
    --   query_params (jsonb): Query parameters for filtering
    --
    -- Query Parameters (optional):
    --   lang (text): Language code for names (de, en, fr, it) - default: 'de'
    --   cluster_max_zoom (int): Max zoom for clustering. NULL disables clustering. default: 8
    --   cluster_low_zoom_offset (int): Extra zoom levels for low-importance POIs. default: 2
    --   importance_threshold (int): Importance threshold for high-value POIs (0-100). default: 50
    --   cluster_radius_m (float): Cluster radius in meters at cluster_ref_zoom. NULL = auto
    --   cluster_ref_zoom (int): Reference zoom for cluster_radius_m. default: 8
    --   max_features (int): Max features per tile (applied after clustering). default: null (no limit)
    --
    -- Default clustering behavior:
    --   z0-8: All POIs clustered
    --   z9-10: High-importance POIs (>=50) raw, low-importance still clustered
    --   z11+: All POIs raw (no clustering)
    --
    -- Returns:
    --   bytea: MVT (Mapbox Vector Tile) encoded tile data
    --
    -- MVT Feature Schema (consistent for clustered and raw features):
    --   category (jsonb): Full category object for THIS row's category (with parent info)
    --   color (text): Category color (for MapLibre styling)
    --   parent_color (text): Parent category color (optional)
    --   categories_all (jsonb): Array of ALL category objects for this POI
    --   sources (jsonb): Array of organization sources
    --   importance (integer): Importance score of representative POI (0-100)
    --   count (integer): Number of POIs in cluster. Always 1 for raw features
    --   name (text): POI name (empty string when clustered)
    --   slug (text): POI slug (empty string when clustered)

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
      cluster_max_zoom int;
      cluster_low_zoom_offset int;
      importance_threshold int;
      cluster_radius_m float;
      cluster_ref_zoom int;
      max_features_limit int;
      tile_bbox geometry;
      tile_bbox_4326 geometry;
      grid_size float;
    BEGIN
      -- Extract query parameters with defaults
      requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
      cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 8);
      cluster_low_zoom_offset := COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2);
      importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
      cluster_radius_m := (query_params->>'cluster_radius_m')::float;
      cluster_ref_zoom := COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8);
      max_features_limit := (query_params->>'max_features')::int;

      tile_bbox := ST_TileEnvelope(z, x, y);
      tile_bbox_4326 := ST_Transform(tile_bbox, 4326);

      -- Calculate grid size
      -- If cluster_radius_m is provided, it's anchored at cluster_ref_zoom and scaled
      -- Otherwise, use one cell per tile pixel for automatic density-based clustering
      grid_size := COALESCE(
        cluster_radius_m * power(2.0, cluster_ref_zoom - z),
        40075016.0 / (256.0 * power(2, z))
      );

      WITH
      -- OPTIMIZATION 1: Pre-aggregate categories in separate CTE
      poi_categories AS (
        SELECT
          gpc.geo_place_id,
          jsonb_agg(
            jsonb_build_object(
              'slug', cat.slug,
              'identifier', cat.identifier,
              'name', cat.name,
              'color', cat.color
            ) ORDER BY cat."order"
          ) AS categories_all
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        GROUP BY gpc.geo_place_id
      ),

      -- OPTIMIZATION 2: Pre-aggregate sources in separate CTE
      poi_sources AS (
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
      ),

      -- OPTIMIZATION 3: Use LATERAL joins instead of correlated subqueries
      geo_places_with_categories AS (
        -- Flatten POI-category relationships
        -- Each POI appears once per category (multi-category POIs appear multiple times)
        SELECT
          gp.slug,
          gp.location,
          gp.importance,
          gp.elevation,
          gp.country_code,
          gp.detail_type,
          gp.extra,

          -- Dynamic name based on requested language
          CASE requested_language
            WHEN 'de' THEN COALESCE(gp.i18n->>'name_de', gp.name, '')
            WHEN 'en' THEN COALESCE(gp.i18n->>'name_en', gp.name, '')
            WHEN 'fr' THEN COALESCE(gp.i18n->>'name_fr', gp.name, '')
            WHEN 'it' THEN COALESCE(gp.i18n->>'name_it', gp.name, '')
            ELSE COALESCE(gp.name, '')
          END AS name,

          -- Full category object for THIS specific category (one row per category)
          jsonb_build_object(
            'slug', cat.slug,
            'identifier', cat.identifier,
            'name', cat.name,
            'color', cat.color,
            'order', cat."order",
            'parent_slug', parent.slug,
            'parent_color', parent.color
          ) AS category,

          -- Extract color as top-level field for MapLibre
          cat.color AS color,

          -- Parent color for styling
          parent.color AS parent_color,

          -- OPTIMIZATION 4: Use pre-aggregated data with LATERAL (executes once per POI)
          pc.categories_all,
          ps.sources

        FROM geometries_geoplace gp
        INNER JOIN geometries_geoplace_category gpc ON gp.id = gpc.geo_place_id
        INNER JOIN categories_category cat ON gpc.category_id = cat.id
        LEFT JOIN categories_category parent ON cat.parent_id = parent.id

        -- LATERAL joins: execute once per POI, not per row
        LEFT JOIN LATERAL (
          SELECT categories_all FROM poi_categories WHERE geo_place_id = gp.id
        ) pc ON true
        LEFT JOIN LATERAL (
          SELECT sources FROM poi_sources WHERE geo_place_id = gp.id
        ) ps ON true

        WHERE gp.is_public = true
          AND gp.is_active = true
          AND gp.location && tile_bbox_4326
          AND ST_Intersects(gp.location, tile_bbox_4326)
      ),
      clustered_features AS (
        -- Cluster branch: Low-importance POIs within clustering zoom range
        -- Groups by (category, grid_cell)
        SELECT
          ST_AsMVTGeom(
            (array_agg(ST_Transform(location, 3857) ORDER BY importance DESC))[1],
            tile_bbox, 4096, 64, true
          )                                                        AS geom,

          -- Use the most important POI's category as the cluster category
          (array_agg(category ORDER BY importance DESC))[1]       AS category,

          -- Extract color from the most important POI's category
          (array_agg(color ORDER BY importance DESC))[1]          AS color,

          -- Extract parent color
          (array_agg(parent_color ORDER BY importance DESC))[1]   AS parent_color,

          -- OPTIMIZATION: For clusters, skip expensive categories_all/sources aggregation
          -- These fields are only useful for individual POIs (raw features)
          NULL::jsonb AS categories_all,
          NULL::jsonb AS sources,

          (array_agg(importance ORDER BY importance DESC))[1]       AS importance,
          COUNT(DISTINCT slug)::int                                AS count,
          ''::text                                                   AS name,
          ''::text                                                   AS slug

        FROM geo_places_with_categories clustered

        WHERE (
          cluster_max_zoom IS NOT NULL
          AND z <= cluster_max_zoom + cluster_low_zoom_offset
          AND importance < importance_threshold
        )

        GROUP BY
          category,
          ST_SnapToGrid(ST_Transform(location, 3857), grid_size)
      ),
      raw_features AS (
        -- Raw branch: High-importance POIs above cluster_max_zoom, and all POIs above full cutoff
        SELECT
          ST_AsMVTGeom(ST_Transform(location, 3857), tile_bbox, 4096, 64, true) AS geom,
          category                                                  AS category,
          color                                                     AS color,
          parent_color                                              AS parent_color,
          categories_all                                            AS categories_all,
          sources                                                    AS sources,
          importance,
          1                                                        AS count,
          name,
          slug

        FROM geo_places_with_categories

        WHERE (
          cluster_max_zoom IS NULL
          OR z > cluster_max_zoom + cluster_low_zoom_offset
          OR (importance >= importance_threshold AND z > cluster_max_zoom)
        )

        ORDER BY importance DESC
        LIMIT COALESCE(max_features_limit, NULL)::bigint
      )
      SELECT INTO mvt ST_AsMVT(mvt.*, 'geoplaces', 4096, 'geom') FROM (
        SELECT * FROM clustered_features
        UNION ALL
        SELECT * FROM raw_features
      ) mvt
      WHERE geom IS NOT NULL;

      RETURN mvt;
    END;
    $$ LANGUAGE plpgsql STABLE PARALLEL SAFE;


    -- Update function comment with TileJSON metadata
    COMMENT ON FUNCTION get_geoplaces_for_tiles IS $$
    {
      "description": "GeoPlaces vector tiles with category-aware clustering. Groups by (category, grid_cell) at low zoom levels. Multi-category POIs appear in multiple cluster groups. Default: z0-8 clustered, z9-10 mixed, z11+ raw.",
      "minzoom": 0,
      "maxzoom": 20,
      "attribution": "© Wodore",
      "vector_layers": [
        {
          "id": "geoplaces",
          "description": "Points of interest with clustering support",
          "fields": {
            "category": "Object",
            "color": "String",
            "parent_color": "String",
            "categories_all": "Array",
            "sources": "Array",
            "importance": "Number",
            "count": "Number",
            "name": "String",
            "slug": "String"
          }
        }
      ],
      "defaults": {
        "cluster_max_zoom": 8,
        "cluster_low_zoom_offset": 2,
        "importance_threshold": 50,
        "cluster_radius_m": 5000
      }
    }
    $$;


    -- Performance indexes for clustering queries
    -- Covering index for clustering queries (importance + location)
    CREATE INDEX IF NOT EXISTS idx_geoplace_clustered
      ON geometries_geoplace (importance, location)
      WHERE is_public = true AND is_active = true;

    -- Partial index for high-importance places (low zoom tiles)
    CREATE INDEX IF NOT EXISTS idx_geoplace_high_importance
      ON geometries_geoplace (location, importance)
      WHERE is_public = true AND is_active = true AND importance >= 80;

    -- Junction table index for clustering JOINs (CRITICAL for performance)
    CREATE INDEX IF NOT EXISTS idx_geoplace_category_clustering
      ON geometries_geoplace_category (geo_place_id, category_id);

    -- OPTIMIZATION 6: Add missing index for source association lookups
    CREATE INDEX IF NOT EXISTS idx_geoplacesourceassociation_geo_org
      ON geometries_geoplacesourceassociation (geo_place_id, organization_id)
      WHERE organization_id IS NOT NULL;

    -- OPTIMIZATION 7: Covering index for category aggregation
    CREATE INDEX IF NOT EXISTS idx_geoplace_category_covering
      ON geometries_geoplace_category (geo_place_id, category_id);

    -- Grant permissions (already exists, just ensuring)
    GRANT EXECUTE ON FUNCTION get_geoplaces_for_tiles(integer, integer, integer, jsonb) TO PUBLIC;
    """


def revert_geoplaces_tile_function_to_original(reverse_sql):
    return """
    -- Revert to original non-clustered version from migration 0028
    -- This restores the get_geoplaces_for_tiles function to its original implementation

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
      min_importance := COALESCE(
        min_importance_override,
        CASE z
          WHEN 0 THEN 90
          WHEN 1 THEN 90
          WHEN 2 THEN 90
          WHEN 3 THEN 80
          WHEN 4 THEN 80
          WHEN 5 THEN 60
          WHEN 6 THEN 60
          WHEN 7 THEN 25
          WHEN 8 THEN 15
          WHEN 9 THEN 1
          WHEN 10 THEN 1
          WHEN 11 THEN 1
          WHEN 12 THEN 0
          WHEN 13 THEN 0
          WHEN 14 THEN 0
          WHEN 15 THEN 0
          ELSE 0
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
          CASE requested_language
            WHEN 'de' THEN COALESCE(gp.i18n->>'name_de', gp.name, '')
            WHEN 'en' THEN COALESCE(gp.i18n->>'name_en', gp.name, '')
            WHEN 'fr' THEN COALESCE(gp.i18n->>'name_fr', gp.name, '')
            WHEN 'it' THEN COALESCE(gp.i18n->>'name_it', gp.name, '')
            ELSE COALESCE(gp.name, '')
          END as name,
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
          AND (
            categories_array IS NULL
            OR gp.id IN (
              SELECT gpc.geo_place_id
              FROM geometries_geoplace_category gpc
              JOIN categories_category cat ON gpc.category_id = cat.id
              WHERE cat.slug = ANY(categories_array)
            )
          )
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
        ORDER BY gp.importance DESC, RANDOM()
        LIMIT COALESCE(max_features_limit, NULL)::bigint
      )
      SELECT INTO mvt ST_AsMVT(tile, 'geoplaces', 4096, 'geom') FROM (
        SELECT
          ST_AsMVTGeom(
            ST_Transform(fp.location, 3857),
            ST_TileEnvelope(z, x, y),
            4096, 64, true
          ) AS geom,
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
          CASE
            WHEN fields_array IS NULL OR 'categories' = ANY(fields_array)
            THEN fp.categories
            ELSE NULL::jsonb
          END as categories,
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

    -- Restore original comment
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

    -- Clean up performance indexes
    DROP INDEX IF EXISTS idx_geoplace_clustered;
    DROP INDEX IF EXISTS idx_geoplace_high_importance;
    """


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0031_remove_unnamed_default_and_allow_blank_name"),
    ]

    operations = [
        migrations.RunSQL(
            sql=update_geoplaces_tile_function_with_clustering(forwards_sql=None),
            reverse_sql=revert_geoplaces_tile_function_to_original(reverse_sql=None),
        ),
    ]
