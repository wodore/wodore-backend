"""Restore the clustered geoplaces tile function (lost in 0068).

0068 rebuilt ``get_geoplaces_for_tiles`` from 0028's frozen template to
apply the ``detail_type`` → ``kind_slug`` rename — but 0028 predates the
clustering/caching work (0032–0041), so the rebuild silently dropped the
cluster parameters, the ``count``/``color``/``parent_color`` properties,
the DB tile cache usage and the zoom-based raw/cluster split. The admin
tile map (built for the clustered contract) rendered nothing, and the
``tiles_view.py`` docstring kept documenting the lost behavior.

This migration re-creates the function from the 0041 shape (the last
clustered revision — two query paths, precomputed 3857 locations,
static cache INSERT), updated for the current schema and contracts:

* one feature per place (primary category by tree ``order``) — the
  0041 shape joined every ``geoplace_category`` row, rendering
  multi-category places once per category;
* flat client-friendly properties ``category_slug``,
  ``category_identifier``, ``category_order``, ``parent_slug`` (the
  0041 ``category`` jsonb object forced client-side nested lookups);
  the object itself is GONE from the projections — ST_AsMVT flattens
  jsonb objects into top-level keys, so the object's name/slug/color
  shadowed the feature's real columns (duplicate MVT keys);
* the 0028-era category filters survive: ``categories`` (exact OR) and
  ``categories_all`` (exact AND) — plus a new ``category_tree`` filter
  matching a slug against a linked category's self, parent or
  grandparent (kind, contract group or domain): the OSM importer links
  LEAF categories only, so group-level overlay filters
  (``category_tree=accommodation``) must match ancestors;
* ``cluster_radius_m`` defaults to 5000 — in 0041 a missing parameter
  left it NULL, which silently emptied every clustered tile (the grid
  comparisons went NULL) unless the client always sent it;
* exact-token ``fields`` gating (0041's LIKE match let
  ``categories_all`` toggle ``categories``) with the ``category``
  jsonb object OUT of the defaults — at today's POI volume it
  dominates tile size at city zooms; the flat props are the default
  styling surface;
* inner-query parallelism disabled via a transaction-local
  ``set_config`` — the clustered path over hundreds of thousands of
  rows picks parallel plans whose worker tuple queues spill through
  /dev/shm and 500 on small-shm containers (docker default 64 MB);
  serial execution spills to disk and the DB tile cache absorbs
  repeats.

See ``server/apps/geometries/models/tiles_view.py`` for the full
parameter/property contract.
"""

from django.db import migrations

#: 0037's ``CREATE TABLE IF NOT EXISTS`` is a no-op on databases where
#: 0036 already created ``geometries_tile_cache`` — so no migration-fresh
#: database ever carried the ``cache_version`` column and the 0040/0041
#: cache INSERTs (restored here) failed with UndefinedColumn the moment a
#: tile was served (dev databases were patched manually, tests never
#: exercised the cache path). Ensure the column before the function.
CACHE_SCHEMA_SQL = """
ALTER TABLE geometries_tile_cache
    ADD COLUMN IF NOT EXISTS cache_version INT DEFAULT 1;
"""

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
  fields_array TEXT[];
  need_sources BOOLEAN;
  need_categories BOOLEAN;
  need_name BOOLEAN;
  cache_version INT;
  is_clustered_zoom BOOLEAN;
  categories_filter text;
  categories_all_filter text;
  category_tree_filter text;
  categories_array text[];
  categories_all_array text[];
  category_tree_array text[];
BEGIN
  -- The heavy clustered path (hundreds of thousands of rows at z<=6)
  -- picks parallel plans whose worker tuple queues spill through
  -- /dev/shm; small-shm containers (docker default 64 MB) OOM the tile
  -- with "could not resize shared memory segment". Serial execution
  -- spills to disk instead and is fast enough for a DB-cached tile —
  -- disable inner-query parallelism for this call only (transaction-
  -- local, nothing leaks to the connection).
  PERFORM set_config('max_parallel_workers_per_gather', '0', true);

  -- Extract parameters
  requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
  cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 6);
  cluster_low_zoom_offset := COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2);
  importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
  -- 5000 default: a NULL radius emptied every clustered tile in 0041
  -- (NULL grid_size comparisons) unless the client always sent it.
  cluster_radius_m := COALESCE(NULLIF((query_params->>'cluster_radius_m'), '')::float, 5000.0);
  cluster_ref_zoom := COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8);
  max_features_limit := (query_params->>'max_features')::int;
  max_label_zoom := COALESCE(NULLIF((query_params->>'max_label_zoom'), '')::int, 14);
  cache_ttl_days := COALESCE(NULLIF((query_params->>'cache_ttl_days'), '')::int, 7);
  cache_version := COALESCE(NULLIF((query_params->>'cache_version'), '')::int, 1);

  -- Field gating by EXACT token (the 0041-era LIKE match let
  -- "categories_all" toggle "categories" and vice versa). Default
  -- fields carry the flat styling/filtering surface only — the
  -- "category" jsonb object and the "categories"/"sources" arrays
  -- are opt-in (they dominate tile size at city zooms).
  fields_array := COALESCE(
    string_to_array(NULLIF(query_params->>'fields', ''), ','),
    ARRAY['color', 'parent_color', 'parent_slug', 'importance', 'count', 'name', 'slug']
  );
  need_categories := 'categories' = ANY(fields_array);
  need_sources := 'sources' = ANY(fields_array);
  need_name := 'name' = ANY(fields_array);

  IF z < max_label_zoom THEN
    need_name := FALSE;
  END IF;

  -- Category filters: exact-slug OR, exact-slug AND, and subtree OR
  -- (slug matched against a linked category's kind, group or domain).
  -- Comma-separated strings (URL-friendly); the 0028-era ``::text[]"
  -- cast required Postgres array literals (``{a,b}``) and rejected
  -- plain ``a,b`` values.
  categories_filter := query_params->>'categories';
  categories_all_filter := query_params->>'categories_all';
  category_tree_filter := query_params->>'category_tree';
  categories_array := string_to_array(NULLIF(categories_filter, ''), ',');
  categories_all_array := string_to_array(NULLIF(categories_all_filter, ''), ',');
  category_tree_array := string_to_array(NULLIF(category_tree_filter, ''), ',');
  IF categories_array = ARRAY[]::text[] THEN
    categories_array := NULL;
  END IF;
  IF categories_all_array = ARRAY[]::text[] THEN
    categories_all_array := NULL;
  END IF;
  IF category_tree_array = ARRAY[]::text[] THEN
    category_tree_array := NULL;
  END IF;

  -- Clustering active at this zoom level (full zone OR transition zone)
  is_clustered_zoom := (cluster_max_zoom IS NOT NULL AND z <= cluster_max_zoom + cluster_low_zoom_offset);

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
    grid_size := 0;
  ELSIF z > cluster_max_zoom THEN
    grid_at_max_zoom := cluster_radius_m * power(2.0, cluster_ref_zoom - cluster_max_zoom);
    progress := (z::float - cluster_max_zoom::float) / cluster_low_zoom_offset::float;
    grid_size := grid_at_max_zoom + (50.0 - grid_at_max_zoom) * progress;
    grid_size := GREATEST(grid_size, 50.0);
  ELSE
    grid_size := cluster_radius_m * power(2.0, cluster_ref_zoom - z);
  END IF;

  IF grid_size > 0 AND grid_size < 50.0 THEN
    grid_size := 50.0;
  END IF;

  -- Branch: clustered zooms use minimal fields, raw zooms use full fields
  IF is_clustered_zoom THEN
    -- CLUSTERED PATH: one row per place, no categories/sources aggregation
    WITH
    sampled_pois AS MATERIALIZED (
      SELECT
        gp.id,
        gp.slug,
        gp.importance,
        ST_Transform(gp.location, 3857) AS location_3857
      FROM geometries_geoplace gp
      WHERE gp.is_public = true
        AND gp.is_active = true
        AND gp.location && tile_bbox_4326
        -- Categoryless places render nowhere (no color, no icon)
        AND EXISTS (
          SELECT 1 FROM geometries_geoplace_category gpc
          WHERE gpc.geo_place_id = gp.id
        )
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
        AND (
          category_tree_array IS NULL
          OR gp.id IN (
            SELECT gpc.geo_place_id
            FROM geometries_geoplace_category gpc
            JOIN categories_category cat ON gpc.category_id = cat.id
            LEFT JOIN categories_category parent ON cat.parent_id = parent.id
            LEFT JOIN categories_category grandparent ON parent.parent_id = grandparent.id
            WHERE cat.slug = ANY(category_tree_array)
              OR parent.slug = ANY(category_tree_array)
              OR grandparent.slug = ANY(category_tree_array)
          )
        )
    ),

    primary_cat AS (
      -- The place's primary category (lowest tree order) with its group
      SELECT
        ranked.geo_place_id,
        cat.slug AS category_slug,
        cat.identifier AS category_identifier,
        cat."order" AS category_order,
        cat.color AS color,
        parent.slug AS parent_slug,
        parent.color AS parent_color
      FROM (
        SELECT
          gpc.geo_place_id,
          gpc.category_id,
          ROW_NUMBER() OVER (
            PARTITION BY gpc.geo_place_id ORDER BY cat."order", cat.id
          ) AS rn
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        JOIN sampled_pois sp ON sp.id = gpc.geo_place_id
      ) ranked
      JOIN categories_category cat ON ranked.category_id = cat.id
      LEFT JOIN categories_category parent ON cat.parent_id = parent.id
      WHERE ranked.rn = 1
    ),

    places AS (
      SELECT
        sp.id,
        sp.location_3857,
        sp.importance,
        pc.category_slug,
        pc.category_identifier,
        pc.category_order,
        pc.color,
        pc.parent_slug,
        pc.parent_color
      FROM sampled_pois sp
      JOIN primary_cat pc ON pc.geo_place_id = sp.id
    ),

    clustered_features AS (
      SELECT
        ST_AsMVTGeom(
          (array_agg(location_3857 ORDER BY importance DESC))[1],
          tile_bbox, 4096, 64, true
        ) AS geom,
        (array_agg(color ORDER BY importance DESC))[1] AS color,
        (array_agg(parent_color ORDER BY importance DESC))[1] AS parent_color,
        (array_agg(parent_slug ORDER BY importance DESC))[1] AS parent_slug,
        (array_agg(category_slug ORDER BY importance DESC))[1] AS category_slug,
        (array_agg(category_identifier ORDER BY importance DESC))[1] AS category_identifier,
        (array_agg(category_order ORDER BY importance DESC))[1] AS category_order,
        NULL::jsonb AS categories,
        NULL::jsonb AS sources,
        (array_agg(importance ORDER BY importance DESC))[1] AS importance,
        COUNT(*)::int AS count,
        ''::text AS name,
        ''::text AS slug

      FROM places

      -- In full clustering zone (z <= cluster_max_zoom): cluster EVERYTHING
      -- In transition zone (cluster_max_zoom < z <= max+offset): only cluster
      --   low-importance POIs; high-importance ones graduate to raw
      WHERE (
        z <= cluster_max_zoom
        OR importance < importance_threshold
      )
      AND grid_size >= 50

      GROUP BY
        category_identifier,
        ROUND(ST_X(location_3857) / grid_size),
        ROUND(ST_Y(location_3857) / grid_size)
    ),

    raw_features AS (
      SELECT
        ST_AsMVTGeom(location_3857, tile_bbox, 4096, 64, true) AS geom,
        color,
        parent_color,
        parent_slug,
        category_slug,
        category_identifier,
        category_order,
        NULL::jsonb AS categories,
        NULL::jsonb AS sources,
        importance,
        1 AS count,
        ''::text AS name,
        ''::text AS slug

      FROM places

      -- Raw features only in transition zone for high-importance POIs
      -- Full clustering zone has NO raw features at all
      WHERE z > cluster_max_zoom
        AND (importance >= importance_threshold OR grid_size < 50)

      ORDER BY importance DESC
    )

    SELECT INTO mvt ST_AsMVT(mvt.*, 'geoplaces', 4096, 'geom') FROM (
      SELECT * FROM (
        SELECT * FROM clustered_features
        UNION ALL
        SELECT * FROM raw_features
      ) all_features
      WHERE geom IS NOT NULL
    ) mvt;

  ELSE
    -- RAW PATH: full fields with categories/sources aggregation
    WITH
    sampled_pois AS MATERIALIZED (
      SELECT
        gp.id,
        gp.slug,
        gp.importance,
        gp.i18n,
        gp.name,
        ST_Transform(gp.location, 3857) AS location_3857
      FROM geometries_geoplace gp
      WHERE gp.is_public = true
        AND gp.is_active = true
        AND gp.location && tile_bbox_4326
        AND EXISTS (
          SELECT 1 FROM geometries_geoplace_category gpc
          WHERE gpc.geo_place_id = gp.id
        )
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
        AND (
          category_tree_array IS NULL
          OR gp.id IN (
            SELECT gpc.geo_place_id
            FROM geometries_geoplace_category gpc
            JOIN categories_category cat ON gpc.category_id = cat.id
            LEFT JOIN categories_category parent ON cat.parent_id = parent.id
            LEFT JOIN categories_category grandparent ON parent.parent_id = grandparent.id
            WHERE cat.slug = ANY(category_tree_array)
              OR parent.slug = ANY(category_tree_array)
              OR grandparent.slug = ANY(category_tree_array)
          )
        )
    ),

    primary_cat AS (
      SELECT
        ranked.geo_place_id,
        cat.slug AS category_slug,
        cat.identifier AS category_identifier,
        cat."order" AS category_order,
        cat.color AS color,
        parent.slug AS parent_slug,
        parent.color AS parent_color
      FROM (
        SELECT
          gpc.geo_place_id,
          gpc.category_id,
          ROW_NUMBER() OVER (
            PARTITION BY gpc.geo_place_id ORDER BY cat."order", cat.id
          ) AS rn
        FROM geometries_geoplace_category gpc
        JOIN categories_category cat ON gpc.category_id = cat.id
        JOIN sampled_pois sp ON sp.id = gpc.geo_place_id
      ) ranked
      JOIN categories_category cat ON ranked.category_id = cat.id
      LEFT JOIN categories_category parent ON cat.parent_id = parent.id
      WHERE ranked.rn = 1
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
        ) AS categories
      FROM geometries_geoplace_category gpc
      JOIN sampled_pois sp ON sp.id = gpc.geo_place_id
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
      JOIN sampled_pois sp ON sp.id = gsa.geo_place_id
      JOIN organizations_organization o ON gsa.organization_id = o.id
      WHERE o.slug IS NOT NULL
      GROUP BY gsa.geo_place_id
    ),

    places AS (
      SELECT
        sp.id,
        sp.slug,
        sp.location_3857,
        sp.importance,
        sp.i18n,
        sp.name,
        pc.category_slug,
        pc.category_identifier,
        pc.category_order,
        pc.color,
        pc.parent_slug,
        pc.parent_color
      FROM sampled_pois sp
      JOIN primary_cat pc ON pc.geo_place_id = sp.id
    ),

    raw_features AS (
      SELECT
        ST_AsMVTGeom(location_3857, tile_bbox, 4096, 64, true) AS geom,
        color,
        parent_color,
        parent_slug,
        category_slug,
        category_identifier,
        category_order,
        CASE WHEN need_categories THEN pca.categories ELSE NULL::jsonb END AS categories,
        CASE WHEN need_sources THEN pso.sources ELSE NULL::jsonb END AS sources,
        importance,
        1 AS count,

        CASE WHEN need_name THEN
          CASE requested_language
            WHEN 'de' THEN COALESCE(i18n->>'name_de', name, '')
            WHEN 'en' THEN COALESCE(i18n->>'name_en', name, '')
            WHEN 'fr' THEN COALESCE(i18n->>'name_fr', name, '')
            WHEN 'it' THEN COALESCE(i18n->>'name_it', name, '')
            ELSE COALESCE(name, '')
          END
        ELSE ''::text
        END AS name,

        slug

      FROM places
      LEFT JOIN poi_categories pca ON pca.geo_place_id = places.id
      LEFT JOIN poi_sources pso ON pso.geo_place_id = places.id

      ORDER BY importance DESC
      LIMIT COALESCE(max_features_limit, NULL)::bigint
    )

    SELECT INTO mvt ST_AsMVT(mvt.*, 'geoplaces', 4096, 'geom') FROM (
      SELECT * FROM raw_features
      WHERE geom IS NOT NULL
    ) mvt;
  END IF;

  -- Cache the tile (cache_ttl_days <= 0 disables persistence)
  IF cache_ttl_days > 0 THEN
    INSERT INTO geometries_tile_cache (z, x, y, params_hash, tile_data, cache_version, expires_at)
    VALUES (
      get_geoplaces_for_tiles.z,
      get_geoplaces_for_tiles.x,
      get_geoplaces_for_tiles.y,
      cache_key,
      mvt,
      cache_version,
      NOW() + (cache_ttl_days::text || ' days')::interval
    )
    ON CONFLICT ON CONSTRAINT geometries_tile_cache_z_x_y_params_hash_key
    DO UPDATE
    SET tile_data = EXCLUDED.tile_data,
        expires_at = EXCLUDED.expires_at,
        cache_version = EXCLUDED.cache_version;
  END IF;

  RETURN mvt;
END;
$$ LANGUAGE plpgsql VOLATILE PARALLEL SAFE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("geometries", "0075_alter_geoplace_domain"),
    ]

    operations = [
        # BEFORE the function: the cache INSERT it restores needs the
        # column no migration-fresh database carries (see CACHE_SCHEMA_SQL)
        migrations.RunSQL(
            sql=CACHE_SCHEMA_SQL,
            reverse_sql="ALTER TABLE geometries_tile_cache"
            " DROP COLUMN IF EXISTS cache_version;",
        ),
        migrations.RunSQL(
            sql=FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS "
                "get_geoplaces_for_tiles(integer, integer, integer, jsonb) CASCADE"
            ),
        ),
    ]
