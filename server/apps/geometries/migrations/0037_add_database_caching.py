from django.db import migrations


def add_database_caching_layer(forwards_sql):
    return """
    -- Add database-level caching to get_geoplaces_for_tiles function
    -- This provides persistent caching beyond Martin's in-memory cache

    -- Create cache table with TTL and versioning support
    CREATE TABLE IF NOT EXISTS geometries_tile_cache (
        id BIGSERIAL PRIMARY KEY,
        z INT NOT NULL,
        x INT NOT NULL,
        y INT NOT NULL,
        params_hash TEXT NOT NULL,
        tile_data BYTEA NOT NULL,
        cache_version INT DEFAULT 1,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days',
        UNIQUE(z, x, y, params_hash)
    );

    -- Create indexes for cache lookups and cleanup
    CREATE INDEX IF NOT EXISTS idx_tile_cache_lookup ON geometries_tile_cache (z, x, y, params_hash);
    CREATE INDEX IF NOT EXISTS idx_tile_cache_expires ON geometries_tile_cache (expires_at);

    -- Create function to clean old cache entries
    -- days_to_keep: Delete entries older than this many days. Use 0 to delete ALL entries.
    CREATE OR REPLACE FUNCTION cleanup_tile_cache(days_to_keep INT DEFAULT 7) RETURNS bigint AS $$
    DECLARE
        deleted_count bigint;
    BEGIN
        IF days_to_keep = 0 THEN
            DELETE FROM geometries_tile_cache;
        ELSE
            DELETE FROM geometries_tile_cache
            WHERE expires_at < NOW() - (days_to_keep || ' days')::interval;
        END IF;

        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        RETURN deleted_count;
    END;
    $$ LANGUAGE plpgsql;

    -- Update get_geoplaces_for_tiles to use caching
    -- NOTE: Function must be VOLATILE to allow INSERT operations for caching
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
      max_label_zoom int;
      tile_bbox geometry;
      tile_bbox_4326 geometry;
      grid_size float;
      cache_key text;
      cached_tile bytea;
      cache_ttl_days INT;
      fields_str TEXT;
      need_sources BOOLEAN;
      need_categories BOOLEAN;
      need_name BOOLEAN;
      cache_version INT;
      cache_expires_text TEXT;
    BEGIN
      -- Extract query parameters with defaults
      requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
      cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 8);
      cluster_low_zoom_offset := COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2);
      importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
      cluster_radius_m := (query_params->>'cluster_radius_m')::float;
      cluster_ref_zoom := COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8);
      max_features_limit := (query_params->>'max_features')::int;
      max_label_zoom := COALESCE(NULLIF((query_params->>'max_label_zoom'), '')::int, 14);
      cache_ttl_days := COALESCE(NULLIF((query_params->>'cache_ttl_days'), '')::int, 7);
      cache_version := COALESCE(NULLIF((query_params->>'cache_version'), '')::int, 1);

      -- Parse fields parameter for optimization
      fields_str := COALESCE(query_params->>'fields', 'category,color,icon,importance,count,name,slug');
      need_sources := fields_str LIKE '%sources%';
      need_categories := fields_str LIKE '%categories%';
      need_name := fields_str LIKE '%name%';

      -- Show labels at HIGHER zooms (above max_label_zoom)
      IF z < max_label_zoom THEN
        need_name := FALSE;
      END IF;

      -- Generate cache key from tile coordinates, params, and version
      cache_key := md5(query_params::text || cache_version::text);

      -- Try to get cached tile first (respect TTL)
      SELECT tile_data INTO cached_tile
      FROM geometries_tile_cache cache
      WHERE cache.z = get_geoplaces_for_tiles.z
        AND cache.x = get_geoplaces_for_tiles.x
        AND cache.y = get_geoplaces_for_tiles.y
        AND cache.params_hash = cache_key
        AND cache.expires_at > NOW();

      IF cached_tile IS NOT NULL THEN
        RETURN cached_tile;
      END IF;

      -- Cache miss - generate tile
      tile_bbox := ST_TileEnvelope(z, x, y);
      tile_bbox_4326 := ST_Transform(tile_bbox, 4326);

      -- Dynamic cluster radius calculation
      -- User-specified mode: cluster_radius_m anchored at cluster_ref_zoom, interpolates to 50m at max clustering zoom
      -- Automatic mode: 80km at z8, interpolates toward 0 at max clustering zoom
      IF cluster_radius_m IS NOT NULL THEN
        IF z <= cluster_max_zoom + cluster_low_zoom_offset THEN
          IF z <= cluster_ref_zoom THEN
            -- Below reference zoom: scale up (more aggressive clustering)
            grid_size := cluster_radius_m * power(2.0, cluster_ref_zoom - z);
          ELSE
            -- Above reference zoom: interpolate toward 50m
            DECLARE
              zoom_range INT;
              progress FLOAT;
            BEGIN
              zoom_range := (cluster_max_zoom + cluster_low_zoom_offset) - cluster_ref_zoom;
              progress := (z::float - cluster_ref_zoom::float) / zoom_range::float;
              grid_size := cluster_radius_m + (50.0 - cluster_radius_m) * progress;
            END;
          END IF;
        ELSE
          grid_size := 0;
        END IF;
      ELSE
        -- Automatic mode
        IF z <= cluster_max_zoom THEN
          grid_size := 80000.0 / power(2.0, z - cluster_ref_zoom);
        ELSIF z <= cluster_max_zoom + cluster_low_zoom_offset THEN
          grid_size := 80000.0 * (1 - (z::float - cluster_max_zoom::float) / cluster_low_zoom_offset::float);
        ELSE
          grid_size := 0;
        END IF;
      END IF;

      -- Ensure minimum grid size for meaningful clustering
      IF grid_size > 0 AND grid_size < 50.0 THEN
        grid_size := 50.0;
      END IF;

      WITH
      -- OPTIMIZATION: Step 1 - Random sample to prevent memory issues
      sampled_pois AS (
        SELECT
          gp.id,
          gp.slug,
          gp.location,
          gp.importance,
          gp.elevation,
          gp.country_code,
          gp.detail_type,
          gp.extra,
          gp.name,
          gp.i18n,
          gpc.geo_place_id,
          gpc.category_id
        FROM geometries_geoplace gp
        INNER JOIN geometries_geoplace_category gpc ON gp.id = gpc.geo_place_id
        WHERE gp.is_public = true
          AND gp.is_active = true
          AND gp.location && tile_bbox_4326
          AND ST_Intersects(gp.location, tile_bbox_4326)
        ORDER BY RANDOM()
        LIMIT 50000
      ),

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

      geo_places_with_categories AS (
        SELECT
          sp.slug,
          sp.location,
          sp.importance,
          sp.elevation,
          sp.country_code,
          sp.detail_type,
          sp.extra,

          -- Only compute name if needed and below max_label_zoom
          CASE WHEN need_name THEN
            CASE requested_language
              WHEN 'de' THEN COALESCE(sp.i18n->>'name_de', sp.name, '')
              WHEN 'en' THEN COALESCE(sp.i18n->>'name_en', sp.name, '')
              WHEN 'fr' THEN COALESCE(sp.i18n->>'name_fr', sp.name, '')
              WHEN 'it' THEN COALESCE(sp.i18n->>'name_it', sp.name, '')
              ELSE COALESCE(sp.name, '')
            END
          ELSE ''::text
          END AS name,

          jsonb_build_object(
            'slug', cat.slug,
            'identifier', cat.identifier,
            'name', cat.name,
            'color', cat.color,
            'order', cat."order",
            'parent_slug', parent.slug,
            'parent_color', parent.color
          ) AS category,

          cat.color AS color,
          parent.color AS parent_color,
          -- Only include categories_all if requested
          CASE WHEN need_categories THEN pc.categories_all ELSE NULL::jsonb END AS categories_all,
          -- Only include sources if requested
          CASE WHEN need_sources THEN ps.sources ELSE NULL::jsonb END AS sources

        FROM sampled_pois sp
        INNER JOIN categories_category cat ON sp.category_id = cat.id
        LEFT JOIN categories_category parent ON cat.parent_id = parent.id

        LEFT JOIN LATERAL (
          SELECT categories_all FROM poi_categories WHERE geo_place_id = sp.geo_place_id
        ) pc ON true
        LEFT JOIN LATERAL (
          SELECT sources FROM poi_sources WHERE geo_place_id = sp.geo_place_id
        ) ps ON true
      ),
      clustered_features AS (
        SELECT
          ST_AsMVTGeom(
            (array_agg(ST_Transform(location, 3857) ORDER BY importance DESC))[1],
            tile_bbox, 4096, 64, true
          ) AS geom,
          (array_agg(category ORDER BY importance DESC))[1] AS category,
          (array_agg(color ORDER BY importance DESC))[1] AS color,
          (array_agg(parent_color ORDER BY importance DESC))[1] AS parent_color,
          NULL::jsonb AS categories_all,
          NULL::jsonb AS sources,
          (array_agg(importance ORDER BY importance DESC))[1] AS importance,
          COUNT(DISTINCT slug)::int AS count,
          ''::text AS name,
          ''::text AS slug

        FROM geo_places_with_categories clustered

        WHERE (
          cluster_max_zoom IS NOT NULL
          AND z <= cluster_max_zoom + cluster_low_zoom_offset
          AND importance < importance_threshold
          AND grid_size >= 50
        )

        GROUP BY
          category,
          ST_SnapToGrid(ST_Transform(location, 3857), grid_size)
      ),
      raw_features AS (
        SELECT
          ST_AsMVTGeom(ST_Transform(location, 3857), tile_bbox, 4096, 64, true) AS geom,
          category AS category,
          color AS color,
          parent_color AS parent_color,
          categories_all AS categories_all,
          sources AS sources,
          importance,
          1 AS count,
          name,
          slug

        FROM geo_places_with_categories

        WHERE (
          cluster_max_zoom IS NULL
          OR z > cluster_max_zoom + cluster_low_zoom_offset
          OR (importance >= importance_threshold AND z > cluster_max_zoom)
          OR grid_size < 50
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

      -- Cache the generated tile with TTL
      cache_expires_text := cache_ttl_days::text || ' days';

      EXECUTE format(
        'INSERT INTO geometries_tile_cache (z, x, y, params_hash, tile_data, cache_version, expires_at)
         VALUES (%L, %L, %L, %L, $1, %L, NOW() + %L::interval)
         ON CONFLICT (z, x, y, params_hash) DO UPDATE
         SET tile_data = EXCLUDED.tile_data,
             expires_at = EXCLUDED.expires_at,
             cache_version = EXCLUDED.cache_version',
        z, x, y, cache_key, cache_version, cache_expires_text
      ) USING mvt;

      RETURN mvt;
    END;
    $$ LANGUAGE plpgsql VOLATILE PARALLEL SAFE;

    -- Update function comment with full parameter documentation
    COMMENT ON FUNCTION get_geoplaces_for_tiles IS $$
    {
      "description": "GeoPlaces vector tiles with category-aware clustering and database caching. Groups by (category, grid_cell) at low zoom levels. Multi-category POIs appear in multiple cluster groups. Labels shown at higher zooms (max_label_zoom+). Default: z0-8 clustered, z9-10 mixed, z11+ raw. Tiles cached in database with configurable TTL.",
      "minzoom": 0,
      "maxzoom": 20,
      "attribution": "© Wodore",
      "vector_layers": [
        {
          "id": "geoplaces",
          "description": "Points of interest with clustering support and database caching",
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
      "parameters": {
        "lang": "Language code for names (de, en, fr, it). Default: 'de'",
        "cluster_max_zoom": "Max zoom for clustering. NULL = disabled. Default: 8",
        "cluster_low_zoom_offset": "Extra zoom levels for low-importance POIs. Default: 2",
        "importance_threshold": "Importance threshold for high-value POIs (0-100). Default: 50",
        "cluster_radius_m": "Cluster radius in meters at cluster_ref_zoom. NULL = auto (80km at z8).",
        "cluster_ref_zoom": "Reference zoom for cluster_radius_m. Default: 8",
        "max_features": "Max features per tile. NULL = unlimited. Default: null",
        "max_label_zoom": "Show labels at this zoom level and above. Default: 14",
        "cache_ttl_days": "Cache time-to-live in days. Default: 7",
        "cache_version": "Cache version for invalidation. Increment to invalidate ALL cached tiles. Default: 1",
        "fields": "Comma-separated fields to include (optimization). Default: all fields"
      },
      "defaults": {
        "cluster_max_zoom": 8,
        "cluster_low_zoom_offset": 2,
        "importance_threshold": 50,
        "cluster_ref_zoom": 8,
        "max_label_zoom": 14,
        "cache_ttl_days": 7
      },
      "caching": {
        "type": "Database with TTL",
        "cache_key": "MD5(query_params + cache_version)",
        "default_ttl": "7 days",
        "cache_version": {
          "parameter": "cache_version (int)",
          "default": "1",
          "purpose": "Global cache invalidation - increment this parameter to invalidate ALL cached tiles",
          "usage": "When to increment: 1) Schema changes, 2) Clustering algorithm updates, 3) Data imports requiring refresh, 4) Bug fixes in tile generation",
          "how_to_use": "Add cache_version=2 to your tile request URL to use version 2 (or any value)",
          "example": "?cache_version=2",
          "impact": "Each cache_version value maintains a separate cache. Old versions can be cleaned up via TTL."
        }
      }
    }
    $$;

    -- Grant permissions
    GRANT SELECT ON geometries_tile_cache TO PUBLIC;
    GRANT EXECUTE ON FUNCTION cleanup_tile_cache(INT) TO PUBLIC;
    GRANT EXECUTE ON FUNCTION get_geoplaces_for_tiles(integer, integer, integer, jsonb) TO PUBLIC;
    """


def revert_to_uncached_function(reverse_sql):
    return """
    -- Remove caching layer and restore to version without caching

    -- Drop cleanup function
    DROP FUNCTION IF EXISTS cleanup_tile_cache(INT);

    -- Drop cache table
    DROP TABLE IF EXISTS geometries_tile_cache;

    -- Restore uncached version (basic clustering without cache)
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
      max_label_zoom int;
      tile_bbox geometry;
      tile_bbox_4326 geometry;
      grid_size float;
      fields_str TEXT;
      need_sources BOOLEAN;
      need_categories BOOLEAN;
      need_name BOOLEAN;
    BEGIN
      requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
      cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 8);
      cluster_low_zoom_offset := COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2);
      importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
      cluster_radius_m := (query_params->>'cluster_radius_m')::float;
      cluster_ref_zoom := COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8);
      max_features_limit := (query_params->>'max_features')::int;
      max_label_zoom := COALESCE(NULLIF((query_params->>'max_label_zoom'), '')::int, 14);

      fields_str := COALESCE(query_params->>'fields', 'category,color,icon,importance,count,name,slug');
      need_sources := fields_str LIKE '%sources%';
      need_categories := fields_str LIKE '%categories%';
      need_name := fields_str LIKE '%name%';

      IF z < max_label_zoom THEN
        need_name := FALSE;
      END IF;

      tile_bbox := ST_TileEnvelope(z, x, y);
      tile_bbox_4326 := ST_Transform(tile_bbox, 4326);

      IF cluster_radius_m IS NOT NULL THEN
        IF z <= cluster_max_zoom + cluster_low_zoom_offset THEN
          IF z <= cluster_ref_zoom THEN
            grid_size := cluster_radius_m * power(2.0, cluster_ref_zoom - z);
          ELSE
            DECLARE
              zoom_range INT;
              progress FLOAT;
            BEGIN
              zoom_range := (cluster_max_zoom + cluster_low_zoom_offset) - cluster_ref_zoom;
              progress := (z::float - cluster_ref_zoom::float) / zoom_range::float;
              grid_size := cluster_radius_m + (50.0 - cluster_radius_m) * progress;
            END;
          END IF;
        ELSE
          grid_size := 0;
        END IF;
      ELSE
        IF z <= cluster_max_zoom THEN
          grid_size := 80000.0 / power(2.0, z - cluster_ref_zoom);
        ELSIF z <= cluster_max_zoom + cluster_low_zoom_offset THEN
          grid_size := 80000.0 * (1 - (z::float - cluster_max_zoom::float) / cluster_low_zoom_offset::float);
        ELSE
          grid_size := 0;
        END IF;
      END IF;

      IF grid_size > 0 AND grid_size < 50.0 THEN
        grid_size := 50.0;
      END IF;

      WITH
      -- OPTIMIZATION: Step 1 - Random sample to prevent memory issues
      sampled_pois AS (
        SELECT
          gp.id,
          gp.slug,
          gp.location,
          gp.importance,
          gp.elevation,
          gp.country_code,
          gp.detail_type,
          gp.extra,
          gp.name,
          gp.i18n,
          gpc.geo_place_id,
          gpc.category_id
        FROM geometries_geoplace gp
        INNER JOIN geometries_geoplace_category gpc ON gp.id = gpc.geo_place_id
        WHERE gp.is_public = true
          AND gp.is_active = true
          AND gp.location && tile_bbox_4326
          AND ST_Intersects(gp.location, tile_bbox_4326)
        ORDER BY RANDOM()
        LIMIT 50000
      ),

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

      geo_places_with_categories AS (
        SELECT
          sp.slug,
          sp.location,
          sp.importance,
          sp.elevation,
          sp.country_code,
          sp.detail_type,
          sp.extra,

          CASE WHEN need_name THEN
            CASE requested_language
              WHEN 'de' THEN COALESCE(sp.i18n->>'name_de', sp.name, '')
              WHEN 'en' THEN COALESCE(sp.i18n->>'name_en', sp.name, '')
              WHEN 'fr' THEN COALESCE(sp.i18n->>'name_fr', sp.name, '')
              WHEN 'it' THEN COALESCE(sp.i18n->>'name_it', sp.name, '')
              ELSE COALESCE(sp.name, '')
            END
          ELSE ''::text
          END AS name,

          jsonb_build_object(
            'slug', cat.slug,
            'identifier', cat.identifier,
            'name', cat.name,
            'color', cat.color,
            'order', cat."order",
            'parent_slug', parent.slug,
            'parent_color', parent.color
          ) AS category,

          cat.color AS color,
          parent.color AS parent_color,
          CASE WHEN need_categories THEN pc.categories_all ELSE NULL::jsonb END AS categories_all,
          CASE WHEN need_sources THEN ps.sources ELSE NULL::jsonb END AS sources

        FROM sampled_pois sp
        INNER JOIN categories_category cat ON sp.category_id = cat.id
        LEFT JOIN categories_category parent ON cat.parent_id = parent.id

        LEFT JOIN LATERAL (
          SELECT categories_all FROM poi_categories WHERE geo_place_id = sp.geo_place_id
        ) pc ON true
        LEFT JOIN LATERAL (
          SELECT sources FROM poi_sources WHERE geo_place_id = sp.geo_place_id
        ) ps ON true
      ),
      clustered_features AS (
        SELECT
          ST_AsMVTGeom(
            (array_agg(ST_Transform(location, 3857) ORDER BY importance DESC))[1],
            tile_bbox, 4096, 64, true
          ) AS geom,
          (array_agg(category ORDER BY importance DESC))[1] AS category,
          (array_agg(color ORDER BY importance DESC))[1] AS color,
          (array_agg(parent_color ORDER BY importance DESC))[1] AS parent_color,
          NULL::jsonb AS categories_all,
          NULL::jsonb AS sources,
          (array_agg(importance ORDER BY importance DESC))[1] AS importance,
          COUNT(DISTINCT slug)::int AS count,
          ''::text AS name,
          ''::text AS slug

        FROM geo_places_with_categories clustered

        WHERE (
          cluster_max_zoom IS NOT NULL
          AND z <= cluster_max_zoom + cluster_low_zoom_offset
          AND importance < importance_threshold
          AND grid_size >= 50
        )

        GROUP BY
          category,
          ST_SnapToGrid(ST_Transform(location, 3857), grid_size)
      ),
      raw_features AS (
        SELECT
          ST_AsMVTGeom(ST_Transform(location, 3857), tile_bbox, 4096, 64, true) AS geom,
          category AS category,
          color AS color,
          parent_color AS parent_color,
          categories_all AS categories_all,
          sources AS sources,
          importance,
          1 AS count,
          name,
          slug

        FROM geo_places_with_categories

        WHERE (
          cluster_max_zoom IS NULL
          OR z > cluster_max_zoom + cluster_low_zoom_offset
          OR (importance >= importance_threshold AND z > cluster_max_zoom)
          OR grid_size < 50
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

    -- Restore original comment
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
    """


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0036_add_tile_caching"),
    ]

    operations = [
        migrations.RunSQL(
            sql=add_database_caching_layer(forwards_sql=None),
            reverse_sql=revert_to_uncached_function(reverse_sql=None),
        ),
    ]
