# Generated manually

from django.db import migrations

# Adds the hut-level ``type_standard_identifier`` property to
# ``get_availability_for_tiles`` features so the accommodation-type filter
# (seeded in map_seed: mapProperty ``type_standard_identifier``) also applies
# to the availability strip layers, not just the hut pins.
#
# Full CREATE OR REPLACE of the function (SQL functions replace wholesale —
# same carry-the-full-body pattern as the geoplaces migrations 0038/0041).

FUNCTION_SQL = """
-- Tile function v2 (delta vs 0016: type_standard_identifier on features).
-- VOLATILE because it writes to the tile cache.
CREATE OR REPLACE FUNCTION get_availability_for_tiles(
  z integer,
  x integer,
  y integer,
  query_params jsonb DEFAULT '{}'::jsonb
)
RETURNS bytea AS $fn$
DECLARE
  mvt bytea;
  date_text text;
  date_valid boolean;
  start_date date;
  req_days int;
  days_max_zoom int;
  eff_days int;
  cache_ttl int;
  cache_key text;
  cached_tile bytea;
  tile_bbox geometry;
BEGIN
  -- ── Parameters (regex-guarded: bad input never 500s)
  -- date is REQUIRED: "now" logic belongs to the client so every tile
  -- URL is cacheable. Missing/invalid date → empty tile, not a default.
  date_text := query_params->>'date';
  date_valid := FALSE;
  IF date_text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
    BEGIN
      start_date := date_text::date;
      date_valid := TRUE;
    EXCEPTION WHEN invalid_text_representation OR datetime_field_overflow THEN
      date_valid := FALSE;  -- e.g. 2026-02-30 passes the regex, not the cast
    END;
  END IF;

  IF NOT date_valid THEN
    RETURN ''::bytea;
  END IF;

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
    SELECT h.id, h.slug, h.location, h.hut_type_open_id, h.hut_type_closed_id,
           ht_open.identifier AS type_standard_identifier
    FROM huts_hut h
    LEFT JOIN categories_category ht_open ON ht_open.id = h.hut_type_open_id
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
           MAX(h.type_standard_identifier) AS type_standard_identifier,
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
"""

# Reverse is a no-op: migration 0016 owns the function; rolling back this
# additive property does not need to recreate the older body.


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0016_add_availability_tile_function"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
