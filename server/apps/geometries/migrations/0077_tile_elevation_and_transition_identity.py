"""Shared cluster membership, elevation in tiles, transition identity.

Three coordinated changes for the amenity-popups feature set, keeping
cluster membership EXACTLY in sync between tiles and the new
``/v1/geoplaces/near`` endpoint by construction:

* ``geoplaces_cluster_grid_size(z, params)`` — the cluster grid-size
  formula as a pure SQL function (full zone scaling, hybrid-band
  interpolation toward 50 m, 0 beyond the band). The single definition
  the tile function and the near endpoint share; the formula the tile
  function used to inline in plpgsql is GONE from it.
* ``geoplaces_cluster_membership(z, bounds, params)`` — one row per
  visible place (public + active + categorised, exact/subtree category
  filters, optional bbox prefilter) with its primary category,
  language-resolved name, elevation, 3857 location, grid cell
  (``ROUND(coord / grid_size)``) and the hybrid-band ``is_clustered``
  flag. ``get_geoplaces_for_tiles``' clustered path now aggregates
  these rows (clusters = ``is_clustered`` grouped by category+cell,
  graduated twin = ``NOT is_clustered``); the near endpoint returns one
  cell's members — the counts cannot drift because both read the same
  rows. SYNC comments live at both call sites.
* ``elevation`` joins the tile function's opt-in ``fields`` surface
  (individual features only — raw path AND transition twin; cluster
  features stay NULL). Consumers that request it get fresh tiles
  automatically (the fields change rotates the params-hash cache key);
  everyone else's tiles stay byte-identical.
* the transition-zone raw twin now carries the real ``slug``
  (unconditional) and the language-resolved ``name`` (still gated by
  ``max_label_zoom``) instead of the ``''`` literals 0076 shipped —
  hybrid-band individual markers had no identity for promoteId,
  feature-state or popup lookups.

The identity fix rides no query param, so cached tiles under unchanged
params would serve empty-identity twins until their TTL — the
migration purges ``geometries_tile_cache`` (decisive for every param
combination at once; mechanism documented in ``tiles_view.py``).

See ``server/apps/geometries/api_near.py`` (the near endpoint) and the
openspec change ``add-geoplaces-near`` for the full contract.
"""

from django.db import migrations

#: Stale rows carry the empty-identity transition twins (and no
#: elevation); every param combination is affected at once — a plain
#: DELETE beats rotating cache_version per-param-set.
CACHE_PURGE_SQL = "DELETE FROM geometries_tile_cache;"

GRID_SIZE_SQL = """
-- 1/2 The grid-size formula. Pure function of (z, params) — the exact
-- expression the tile function used to inline in plpgsql: full
-- clustering zone grid = cluster_radius_m * 2^(cluster_ref_zoom - z);
-- hybrid band interpolates linearly toward 50 m; beyond the band 0 (no
-- clustering). Never below 50 m while clustering.
CREATE OR REPLACE FUNCTION geoplaces_cluster_grid_size(
  z integer,
  query_params jsonb DEFAULT '{}'::jsonb
)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN z > cfg.cmz + cfg.off THEN 0.0
    ELSE GREATEST(
      CASE
        WHEN z > cfg.cmz THEN
          cfg.radius * power(2.0, cfg.ref - cfg.cmz)
          + (50.0 - cfg.radius * power(2.0, cfg.ref - cfg.cmz))
            * ((z - cfg.cmz)::float / cfg.off::float)
        ELSE cfg.radius * power(2.0, cfg.ref - z)
      END,
      50.0
    )
  END
  FROM (
    SELECT
      COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 6) AS cmz,
      COALESCE(NULLIF((query_params->>'cluster_low_zoom_offset'), '')::int, 2) AS off,
      COALESCE(NULLIF((query_params->>'cluster_radius_m'), '')::float, 5000.0) AS radius,
      COALESCE(NULLIF((query_params->>'cluster_ref_zoom'), '')::int, 8) AS ref
  ) cfg
$$;
"""


MEMBERSHIP_SQL = """
-- 2/2 Cluster membership rows: every visible place at zoom z with its
-- primary category, grid cell and hybrid-band split flag. The tile
-- function aggregates these into cluster features (is_clustered) and
-- the graduated raw twin (NOT is_clustered); the near endpoint returns
-- one cell's members. visibility/category filters are shared verbatim
-- with the tile function's RAW path semantics (leaf links, exact OR /
-- exact AND / subtree ancestor match).
--
-- plpgsql ON PURPOSE (not LANGUAGE sql): parameter extraction into
-- locals gives the membership query plain plan parameters — a SQL
-- function with the filters as CTE columns degrades the array
-- conditions to per-row correlated SubPlans (441k executions, 30x+
-- slower tiles; caught in the 0077 lane benchmark). #variable_conflict
-- keeps the RETURNS TABLE column names unambiguous against the
-- locals.
CREATE OR REPLACE FUNCTION geoplaces_cluster_membership(
  z integer,
  bounds geometry,
  query_params jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (
  id bigint,
  slug text,
  resolved_name text,
  importance integer,
  elevation integer,
  location_3857 geometry,
  category_slug text,
  category_identifier text,
  category_order integer,
  color text,
  parent_slug text,
  parent_color text,
  cell_x double precision,
  cell_y double precision,
  grid_size double precision,
  is_clustered boolean
)
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $membership$
#variable_conflict use_column
DECLARE
  requested_language text;
  cluster_max_zoom int;
  importance_threshold int;
  grid_size double precision;
  categories_array text[];
  categories_all_array text[];
  category_tree_array text[];
BEGIN
  -- SYNC: parameter extraction mirrors get_geoplaces_for_tiles'
  -- plpgsql block (same expressions, same defaults) and
  -- geoplaces_cluster_grid_size (the formula's only home).
  requested_language := COALESCE(NULLIF(query_params->>'lang', ''), 'de');
  cluster_max_zoom := COALESCE(NULLIF((query_params->>'cluster_max_zoom'), '')::int, 6);
  importance_threshold := COALESCE(NULLIF((query_params->>'importance_threshold'), '')::int, 50);
  grid_size := geoplaces_cluster_grid_size(z, query_params);
  categories_array := string_to_array(NULLIF(query_params->>'categories', ''), ',');
  categories_all_array := string_to_array(NULLIF(query_params->>'categories_all', ''), ',');
  category_tree_array := string_to_array(NULLIF(query_params->>'category_tree', ''), ',');
  IF categories_array = ARRAY[]::text[] THEN
    categories_array := NULL;
  END IF;
  IF categories_all_array = ARRAY[]::text[] THEN
    categories_all_array := NULL;
  END IF;
  IF category_tree_array = ARRAY[]::text[] THEN
    category_tree_array := NULL;
  END IF;

  RETURN QUERY
  WITH
  sampled AS (
    SELECT
      gp.id,
      gp.slug,
      gp.importance,
      gp.elevation,
      CASE requested_language
        WHEN 'de' THEN COALESCE(gp.i18n->>'name_de', gp.name, '')
        WHEN 'en' THEN COALESCE(gp.i18n->>'name_en', gp.name, '')
        WHEN 'fr' THEN COALESCE(gp.i18n->>'name_fr', gp.name, '')
        WHEN 'it' THEN COALESCE(gp.i18n->>'name_it', gp.name, '')
        ELSE COALESCE(gp.name, '')
      END AS resolved_name,
      ST_Transform(gp.location, 3857) AS location_3857
    FROM geometries_geoplace gp
    WHERE gp.is_public = true
      AND gp.is_active = true
      -- Bbox prefilter (4326, GIST-indexed on location): the tile
      -- function passes the tile bbox, the near endpoint a box around
      -- the anchor/cell. REQUIRED — a ``bounds IS NULL OR ...`` guard
      -- would defeat the index and seq-scan 440k rows per tile, and a
      -- CTE-join formulation degrades the array filters to per-row
      -- SubPlans (both caught in the 0077 benchmark).
      AND gp.location && bounds
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
    -- The place's primary category (lowest tree order, id tiebreak)
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
      JOIN sampled sp ON sp.id = gpc.geo_place_id
    ) ranked
    JOIN categories_category cat ON ranked.category_id = cat.id
    LEFT JOIN categories_category parent ON cat.parent_id = parent.id
    WHERE ranked.rn = 1
  )

  SELECT
    sp.id::bigint,
    sp.slug::text,
    sp.resolved_name::text,
    sp.importance::integer,
    sp.elevation,
    sp.location_3857,
    pc.category_slug::text,
    pc.category_identifier::text,
    pc.category_order::integer,
    pc.color::text,
    pc.parent_slug::text,
    pc.parent_color::text,
    -- Cell snap (NULL beyond the clustering band — grid_size 0):
    -- the SAME expression the tile aggregation groups by; the near
    -- endpoint matches its anchor against these cells.
    CASE WHEN grid_size >= 50
      THEN ROUND(ST_X(sp.location_3857) / grid_size)
    END AS cell_x,
    CASE WHEN grid_size >= 50
      THEN ROUND(ST_Y(sp.location_3857) / grid_size)
    END AS cell_y,
    grid_size,
    -- Hybrid split: full zone clusters everything; the transition
    -- band keeps only importance < threshold clustered (high
    -- importance graduates to raw features — NOT is_clustered).
    (
      (z <= cluster_max_zoom OR sp.importance < importance_threshold)
      AND grid_size >= 50
    ) AS is_clustered
  FROM sampled sp
  JOIN primary_cat pc ON pc.geo_place_id = sp.id;
END;
$membership$;
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
  cache_key text;
  cached_tile bytea;
  cache_ttl_days INT;
  fields_array TEXT[];
  need_sources BOOLEAN;
  need_categories BOOLEAN;
  need_name BOOLEAN;
  need_elevation BOOLEAN;
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
  need_elevation := 'elevation' = ANY(fields_array);

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

  IF is_clustered_zoom THEN
    -- CLUSTERED PATH: membership via the SHARED helper
    -- SYNC: geoplaces_cluster_membership (this migration) is the
    -- single source of truth for grid size (geoplaces_cluster_grid_
    -- size), cell snapping, the hybrid importance split and the
    -- visibility/category filters. The /v1/geoplaces/near endpoint
    -- queries the same helper — cluster member lists and tile cluster
    -- counts cannot drift apart. Change membership logic THERE,
    -- never here.
    WITH
    membership AS MATERIALIZED (
      SELECT * FROM geoplaces_cluster_membership(z, tile_bbox_4326, query_params)
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
        ''::text AS slug,
        NULL::int AS elevation

      FROM membership

      -- is_clustered (helper column) == the 0076 condition
      -- (z <= cluster_max_zoom OR importance < importance_threshold)
      -- AND grid_size >= 50
      WHERE is_clustered

      GROUP BY
        category_identifier,
        cell_x,
        cell_y
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
        -- Real identity for graduated individuals (empty since 0076:
        -- the twin hardcoded '' name/slug, leaving hybrid-band markers
        -- without slug for promoteId/selection or popup lookups; the
        -- name still respects the max_label_zoom gate).
        CASE WHEN need_name THEN resolved_name ELSE ''::text END AS name,
        slug,
        CASE WHEN need_elevation THEN elevation ELSE NULL::int END AS elevation

      FROM membership

      -- NOT is_clustered == the 0076 twin condition
      -- z > cluster_max_zoom AND (importance >= importance_threshold
      -- OR grid_size < 50): raw features only in the transition zone
      -- for high-importance POIs; full clustering zone has NO raw
      -- features at all.
      WHERE NOT is_clustered

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
        gp.elevation,
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
        sp.elevation,
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

        slug,
        CASE WHEN need_elevation THEN elevation ELSE NULL::int END AS elevation

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
        ("geometries", "0076_restore_clustered_geoplaces_tiles"),
    ]

    operations = [
        # Shared core first: the tile function's clustered path calls
        # geoplaces_cluster_membership at serve time, which calls
        # geoplaces_cluster_grid_size. ONE statement per RunSQL — a
        # multi-statement RunSQL under psycopg3 applies only the last
        # statement (both catches found via --create-db test runs).
        migrations.RunSQL(
            sql=GRID_SIZE_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS geoplaces_cluster_grid_size"
                "(integer, jsonb);"
            ),
        ),
        migrations.RunSQL(
            sql=MEMBERSHIP_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS geoplaces_cluster_membership"
                "(integer, geometry, jsonb);"
            ),
        ),
        # Purge BEFORE the function swap: rows written by the old
        # function must never outlive the deploy that replaces it.
        migrations.RunSQL(
            sql=CACHE_PURGE_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS "
                "get_geoplaces_for_tiles(integer, integer, integer, jsonb) CASCADE"
            ),
        ),
    ]
