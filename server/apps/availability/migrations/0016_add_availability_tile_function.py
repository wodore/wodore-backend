# Generated manually

from django.db import migrations

# Vector tile source for hut availability, served by Martin as the
# `availability` function source (see tile_server/config/martin.yaml).
#
# One feature per hut (point = hut location) with the per-day availability
# series FLATTENED into scalar MVT properties d0..d7_{status,free,total,
# type,type_identifier,type_color} — MVT attributes cannot carry nested
# arrays/objects, and the map style reads them with literal day keys.
#
# Query parameters (URL query string arrives as ``query_params`` jsonb):
#   date=YYYY-MM-DD   start date; frontend-computed. Default: today (UTC).
#   days=N            1..8 (default 4) — days of the flattened series.
#   days_max_zoom=Z   below zoom Z serve only day 0 (default 7; 0 disables
#                     the clamp) — low-zoom tiles stay small + cheap.
#   cache_ttl=S       DB tile-cache TTL in seconds (default 900 = 15 min;
#                     0 disables caching).
#
# Every property for a day outside the window is simply absent (NULLs are
# dropped by ST_AsMVT), and the feature-level ``days`` property reports how
# many day columns the tile carries so styles can guard
# ``["<", day, ["get", "days"]]``.
#
# Structure mirrors get_geoplaces_for_tiles (geometries 0028/0041) with the
# inline cache of geometries 0036/0037: bbox-first hut selection (GIST on
# huts_hut.location), then the (hut_id, availability_date) window join.

FUNCTION_SQL = """
-- Cache table for generated availability tiles
CREATE TABLE IF NOT EXISTS availability_tile_cache (
    id BIGSERIAL PRIMARY KEY,
    z INT NOT NULL,
    x INT NOT NULL,
    y INT NOT NULL,
    params_hash TEXT NOT NULL,
    tile_data BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '15 minutes',
    hits INT DEFAULT 0,
    UNIQUE(z, x, y, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_availability_tile_cache_lookup
  ON availability_tile_cache (z, x, y, params_hash);
CREATE INDEX IF NOT EXISTS idx_availability_tile_cache_expires
  ON availability_tile_cache (expires_at);

COMMENT ON TABLE availability_tile_cache IS
  'DB cache for get_availability_for_tiles (Martin `availability` source)';

-- Housekeeping: delete entries older than ``hours`` (0 = delete all).
CREATE OR REPLACE FUNCTION cleanup_availability_tile_cache(hours INT DEFAULT 24)
RETURNS bigint AS $cleanup$
DECLARE
    deleted_count bigint;
BEGIN
    IF hours = 0 THEN
        DELETE FROM availability_tile_cache;
    ELSE
        DELETE FROM availability_tile_cache
        WHERE expires_at < NOW() - (hours || ' hours')::interval;
    END IF;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$cleanup$ LANGUAGE plpgsql;

-- Tile function. VOLATILE because it writes to the tile cache
-- (same trade-off as get_geoplaces_for_tiles, geometries 0037).
CREATE OR REPLACE FUNCTION get_availability_for_tiles(
  z integer,
  x integer,
  y integer,
  query_params jsonb DEFAULT '{}'::jsonb
)
RETURNS bytea AS $fn$
DECLARE
  mvt bytea;
  start_date date;
  req_days int;
  days_max_zoom int;
  eff_days int;
  cache_ttl int;
  cache_key text;
  cached_tile bytea;
  tile_bbox geometry;
BEGIN
  -- ── Parameters (regex-guarded: bad input falls back to defaults, never 500)
  start_date := CASE
    WHEN query_params->>'date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      THEN (query_params->>'date')::date
    ELSE (now() AT TIME ZONE 'utc')::date
  END;

  req_days := CASE
    WHEN (query_params->>'days') ~ '^[0-9]+$'
      THEN LEAST(GREATEST((query_params->>'days')::int, 1), 8)
    ELSE 4
  END;

  days_max_zoom := CASE
    WHEN (query_params->>'days_max_zoom') ~ '^[0-9]+$'
      THEN (query_params->>'days_max_zoom')::int
    ELSE 7
  END;

  -- Below days_max_zoom only day 0 is served (low-zoom tiles stay small).
  -- days_max_zoom=0 disables the clamp (z < 0 never matches).
  eff_days := CASE WHEN z < days_max_zoom THEN 1 ELSE req_days END;

  cache_ttl := CASE
    WHEN (query_params->>'cache_ttl') ~ '^[0-9]+$'
      THEN (query_params->>'cache_ttl')::int
    ELSE 900
  END;

  -- Cache key: canonical jsonb text of all params except cache_ttl
  -- (the TTL only affects expiry, never the tile content).
  cache_key := md5((query_params - 'cache_ttl')::text);

  -- ── Cache lookup
  IF cache_ttl > 0 THEN
    SELECT tile_data INTO cached_tile
    FROM availability_tile_cache cache
    WHERE cache.z = get_availability_for_tiles.z
      AND cache.x = get_availability_for_tiles.x
      AND cache.y = get_availability_for_tiles.y
      AND cache.params_hash = cache_key
      AND cache.expires_at > NOW();

    IF cached_tile IS NOT NULL THEN
      UPDATE availability_tile_cache cache
      SET hits = cache.hits + 1
      WHERE cache.z = get_availability_for_tiles.z
        AND cache.x = get_availability_for_tiles.x
        AND cache.y = get_availability_for_tiles.y
        AND cache.params_hash = cache_key;
      RETURN cached_tile;
    END IF;
  END IF;

  -- ── Tile generation (bbox-first: GIST filter on huts, then the
  --    (hut_id, availability_date) window join, then the category join)
  tile_bbox := ST_TileEnvelope(z, x, y);

  WITH huts_in_tile AS (
    SELECT h.id, h.slug, h.location, h.hut_type_open_id, h.hut_type_closed_id
    FROM huts_hut h
    WHERE h.is_active = true
      AND h.is_public = true
      AND h.location && ST_Transform(tile_bbox, 4326)
  ),
  win AS (
    SELECT a.hut_id,
           a.availability_date - start_date AS d,
           a.free, a.total, a.occupancy_status,
           ht.identifier AS type_identifier,
           ht.color AS type_color,
           CASE a.hut_type_id
             WHEN h.hut_type_open_id THEN 'standard'
             WHEN h.hut_type_closed_id THEN 'reduced'
           END AS type
    FROM huts_in_tile h
    JOIN availability_hutavailability a
      ON a.hut_id = h.id
     AND a.availability_date >= start_date
     AND a.availability_date <  start_date + eff_days
    LEFT JOIN categories_category ht ON ht.id = a.hut_type_id
  ),
  pivot AS (
    SELECT h.slug,
           MAX(w.total) AS capacity,
           eff_days AS days,
           MAX(CASE w.d WHEN 0 THEN w.occupancy_status END) AS d0_status,
           MAX(CASE w.d WHEN 0 THEN w.free END)             AS d0_free,
           MAX(CASE w.d WHEN 0 THEN w.total END)            AS d0_total,
           MAX(CASE w.d WHEN 0 THEN w.type END)             AS d0_type,
           MAX(CASE w.d WHEN 0 THEN w.type_identifier END)  AS d0_type_identifier,
           MAX(CASE w.d WHEN 0 THEN w.type_color END)       AS d0_type_color,
           MAX(CASE w.d WHEN 1 THEN w.occupancy_status END) AS d1_status,
           MAX(CASE w.d WHEN 1 THEN w.free END)             AS d1_free,
           MAX(CASE w.d WHEN 1 THEN w.total END)            AS d1_total,
           MAX(CASE w.d WHEN 1 THEN w.type END)             AS d1_type,
           MAX(CASE w.d WHEN 1 THEN w.type_identifier END)  AS d1_type_identifier,
           MAX(CASE w.d WHEN 1 THEN w.type_color END)       AS d1_type_color,
           MAX(CASE w.d WHEN 2 THEN w.occupancy_status END) AS d2_status,
           MAX(CASE w.d WHEN 2 THEN w.free END)             AS d2_free,
           MAX(CASE w.d WHEN 2 THEN w.total END)            AS d2_total,
           MAX(CASE w.d WHEN 2 THEN w.type END)             AS d2_type,
           MAX(CASE w.d WHEN 2 THEN w.type_identifier END)  AS d2_type_identifier,
           MAX(CASE w.d WHEN 2 THEN w.type_color END)       AS d2_type_color,
           MAX(CASE w.d WHEN 3 THEN w.occupancy_status END) AS d3_status,
           MAX(CASE w.d WHEN 3 THEN w.free END)             AS d3_free,
           MAX(CASE w.d WHEN 3 THEN w.total END)            AS d3_total,
           MAX(CASE w.d WHEN 3 THEN w.type END)             AS d3_type,
           MAX(CASE w.d WHEN 3 THEN w.type_identifier END)  AS d3_type_identifier,
           MAX(CASE w.d WHEN 3 THEN w.type_color END)       AS d3_type_color,
           MAX(CASE w.d WHEN 4 THEN w.occupancy_status END) AS d4_status,
           MAX(CASE w.d WHEN 4 THEN w.free END)             AS d4_free,
           MAX(CASE w.d WHEN 4 THEN w.total END)            AS d4_total,
           MAX(CASE w.d WHEN 4 THEN w.type END)             AS d4_type,
           MAX(CASE w.d WHEN 4 THEN w.type_identifier END)  AS d4_type_identifier,
           MAX(CASE w.d WHEN 4 THEN w.type_color END)       AS d4_type_color,
           MAX(CASE w.d WHEN 5 THEN w.occupancy_status END) AS d5_status,
           MAX(CASE w.d WHEN 5 THEN w.free END)             AS d5_free,
           MAX(CASE w.d WHEN 5 THEN w.total END)            AS d5_total,
           MAX(CASE w.d WHEN 5 THEN w.type END)             AS d5_type,
           MAX(CASE w.d WHEN 5 THEN w.type_identifier END)  AS d5_type_identifier,
           MAX(CASE w.d WHEN 5 THEN w.type_color END)       AS d5_type_color,
           MAX(CASE w.d WHEN 6 THEN w.occupancy_status END) AS d6_status,
           MAX(CASE w.d WHEN 6 THEN w.free END)             AS d6_free,
           MAX(CASE w.d WHEN 6 THEN w.total END)            AS d6_total,
           MAX(CASE w.d WHEN 6 THEN w.type END)             AS d6_type,
           MAX(CASE w.d WHEN 6 THEN w.type_identifier END)  AS d6_type_identifier,
           MAX(CASE w.d WHEN 6 THEN w.type_color END)       AS d6_type_color,
           MAX(CASE w.d WHEN 7 THEN w.occupancy_status END) AS d7_status,
           MAX(CASE w.d WHEN 7 THEN w.free END)             AS d7_free,
           MAX(CASE w.d WHEN 7 THEN w.total END)            AS d7_total,
           MAX(CASE w.d WHEN 7 THEN w.type END)             AS d7_type,
           MAX(CASE w.d WHEN 7 THEN w.type_identifier END)  AS d7_type_identifier,
           MAX(CASE w.d WHEN 7 THEN w.type_color END)       AS d7_type_color,
           ST_AsMVTGeom(
             ST_Transform(h.location, 3857),
             tile_bbox, 4096, 64, true
           ) AS geom
    FROM huts_in_tile h
    JOIN win w ON w.hut_id = h.id
    GROUP BY h.id, h.slug, h.location
  )
  SELECT ST_AsMVT(p, 'availability', 4096, 'geom')
  INTO mvt
  FROM (SELECT * FROM pivot WHERE geom IS NOT NULL) p;

  -- ── Cache store (empty tiles are cached too — they recompute for free)
  IF cache_ttl > 0 AND mvt IS NOT NULL THEN
    INSERT INTO availability_tile_cache (z, x, y, params_hash, tile_data, expires_at)
    VALUES (
      get_availability_for_tiles.z,
      get_availability_for_tiles.x,
      get_availability_for_tiles.y,
      cache_key,
      mvt,
      NOW() + (cache_ttl || ' seconds')::interval
    )
    ON CONFLICT ON CONSTRAINT availability_tile_cache_z_x_y_params_hash_key
    DO UPDATE SET
      tile_data = EXCLUDED.tile_data,
      created_at = NOW(),
      expires_at = EXCLUDED.expires_at;
  END IF;

  RETURN mvt;
END;
$fn$ LANGUAGE plpgsql VOLATILE;

GRANT EXECUTE ON FUNCTION get_availability_for_tiles(INT, INT, INT, JSONB) TO PUBLIC;
GRANT EXECUTE ON FUNCTION cleanup_availability_tile_cache(INT) TO PUBLIC;
"""

REVERSE_SQL = """
DROP FUNCTION IF EXISTS get_availability_for_tiles(INT, INT, INT, JSONB);
DROP FUNCTION IF EXISTS cleanup_availability_tile_cache(INT);
DROP TABLE IF EXISTS availability_tile_cache;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0015_hutavailability_free_tolerance_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION_SQL, reverse_sql=REVERSE_SQL),
    ]
