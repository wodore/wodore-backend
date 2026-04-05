"""
Fix cluster grid_size transition zone logic.

The previous formula used cluster_ref_zoom as a pivot point in the transition,
which broke when cluster_max_zoom < cluster_ref_zoom (e.g. max_zoom=5, ref_zoom=8).
The transition zone (cluster_max_zoom < z <= max+offset) now uses a simple linear
interpolation independent of cluster_ref_zoom.

Also changes default cluster_max_zoom from 8 to 6.
"""

from django.db import migrations

FUNCTION_SQL = """
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
  grid_at_max_zoom float;
  progress float;
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
  -- Extract parameters
  requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
  cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 6);
  cluster_low_zoom_offset := COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2);
  importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
  cluster_radius_m := (query_params->>'cluster_radius_m')::float;
  cluster_ref_zoom := COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8);
  max_features_limit := (query_params->>'max_features')::int;
  max_label_zoom := COALESCE(NULLIF((query_params->>'max_label_zoom'), '')::int, 14);
  cache_ttl_days := COALESCE(NULLIF((query_params->>'cache_ttl_days'), '')::int, 7);
  cache_version := COALESCE(NULLIF((query_params->>'cache_version'), '')::int, 1);

  fields_str := COALESCE(query_params->>'fields', 'category,color,icon,importance,count,name,slug');
  need_sources := fields_str LIKE '%sources%';
  need_categories := fields_str LIKE '%categories%';
  need_name := fields_str LIKE '%name%';

  IF z < max_label_zoom THEN
    need_name := FALSE;
  END IF;

  -- Cache lookup
  cache_key := md5(query_params::text || cache_version::text);

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

  -- Compute tile bounds
  tile_bbox := ST_TileEnvelope(z, x, y);
  tile_bbox_4326 := ST_Transform(tile_bbox, 4326);

  -- Compute cluster grid size
  -- Three zones:
  --   z <= cluster_max_zoom:              full clustering, grid_size scales with zoom
  --   cluster_max_zoom < z <= max+offset:  transition, grid_size shrinks linearly to 50m
  --   z > max+offset:                      no clustering, grid_size = 0
  IF z > cluster_max_zoom + cluster_low_zoom_offset THEN
    -- Above transition: no clustering
    grid_size := 0;
  ELSIF z > cluster_max_zoom THEN
    -- Transition zone: linear interpolation from full grid_size down to 50m
    grid_at_max_zoom := cluster_radius_m * power(2.0, cluster_ref_zoom - cluster_max_zoom);
    progress := (z::float - cluster_max_zoom::float) / cluster_low_zoom_offset::float;
    grid_size := grid_at_max_zoom + (50.0 - grid_at_max_zoom) * progress;
    grid_size := GREATEST(grid_size, 50.0);
  ELSE
    -- Full clustering zone: grid_size scales with zoom level
    grid_size := cluster_radius_m * power(2.0, cluster_ref_zoom - z);
  END IF;

  IF grid_size > 0 AND grid_size < 50.0 THEN
    grid_size := 50.0;
  END IF;

  WITH
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
      gpc.category_id
    FROM geometries_geoplace gp
    INNER JOIN geometries_geoplace_category gpc ON gp.id = gpc.geo_place_id
    WHERE gp.is_public = true
      AND gp.is_active = true
      AND gp.location && tile_bbox_4326
    ORDER BY md5(gp.id::text)
    LIMIT 50000
  ),

  poi_categories AS (
    SELECT
      sp.id AS geo_place_id,
      jsonb_agg(
        jsonb_build_object(
          'slug', cat.slug,
          'identifier', cat.identifier,
          'name', cat.name,
          'color', cat.color
        ) ORDER BY cat."order"
      ) AS categories_all
    FROM sampled_pois sp
    JOIN geometries_geoplace_category gpc ON sp.id = gpc.geo_place_id
    JOIN categories_category cat ON gpc.category_id = cat.id
    GROUP BY sp.id
  ),

  poi_sources AS (
    SELECT
      sp.id AS geo_place_id,
      jsonb_agg(
        jsonb_build_object(
          'slug', o.slug,
          'source_id', gsa.source_id
        )
      ) AS sources
    FROM sampled_pois sp
    JOIN geometries_geoplacesourceassociation gsa ON sp.id = gsa.geo_place_id
    JOIN organizations_organization o ON gsa.organization_id = o.id
    WHERE o.slug IS NOT NULL
    GROUP BY sp.id
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
    LEFT JOIN poi_categories pc ON sp.id = pc.geo_place_id
    LEFT JOIN poi_sources ps ON sp.id = ps.geo_place_id
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

    FROM geo_places_with_categories

    WHERE (
      cluster_max_zoom IS NOT NULL
      AND z <= cluster_max_zoom + cluster_low_zoom_offset
      AND importance < importance_threshold
      AND grid_size >= 50
    )

    GROUP BY
      category,
      ROUND((ST_X(ST_Transform(location, 3857))) / grid_size),
      ROUND((ST_Y(ST_Transform(location, 3857))) / grid_size)
  ),

  raw_features AS (
    SELECT
      ST_AsMVTGeom(ST_Transform(location, 3857), tile_bbox, 4096, 64, true) AS geom,
      category,
      color,
      parent_color,
      categories_all,
      sources,
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
    SELECT * FROM (
      SELECT * FROM clustered_features
      UNION ALL
      SELECT * FROM raw_features
    ) all_features
    WHERE geom IS NOT NULL
    LIMIT COALESCE(max_features_limit, 100000)::bigint
  ) mvt;

  -- Cache the tile
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0039_reapply_optimized_tile_function"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FUNCTION_SQL,
            reverse_sql="SELECT 1;",  # Non-destructive, no meaningful reverse
        ),
    ]
