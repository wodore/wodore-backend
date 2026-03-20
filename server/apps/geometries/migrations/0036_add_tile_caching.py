# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('geometries', '0032_add_poi_clustering'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Create tile cache table
            CREATE TABLE IF NOT EXISTS geometries_tile_cache (
                id BIGSERIAL PRIMARY KEY,
                z INT NOT NULL,
                x INT NOT NULL,
                y INT NOT NULL,
                params_hash TEXT NOT NULL,
                tile_data BYTEA NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                hits INT DEFAULT 0,

                -- Constraint to ensure one cached tile per unique combination
                UNIQUE(z, x, y, params_hash)
            );

            -- Index for cache lookups (most common operation)
            CREATE INDEX IF NOT EXISTS idx_tile_cache_lookup
              ON geometries_tile_cache (z, x, y, params_hash);

            -- Index for TTL-based cleanup (removes old entries)
            CREATE INDEX IF NOT EXISTS idx_tile_cache_ttl
              ON geometries_tile_cache (created_at);

            -- Add comment
            COMMENT ON TABLE geometries_tile_cache IS 'Cache for generated vector tiles to improve performance';

            -- Create wrapper function with caching support
            CREATE OR REPLACE FUNCTION get_geoplaces_for_tiles_cached(
              z INT,
              x INT,
              y INT,
              query_params JSONB DEFAULT '{}'::jsonb
            )
            RETURNS BYTEA AS $$
            DECLARE
              cached_tile BYTEA;
              params_hash TEXT;
              cache_ttl_seconds INT;
              use_cache BOOLEAN;
              last_modified TIMESTAMPTZ;
            BEGIN
              -- Extract TTL parameter (default 3600 seconds = 1 hour)
              cache_ttl_seconds := COALESCE(
                NULLIF((query_params->>'cache_ttl'), '')::INT,
                3600
              );

              -- Check if caching is disabled (cache_ttl = 0)
              use_cache := cache_ttl_seconds > 0;

              -- Calculate hash of query parameters (excluding cache_ttl itself)
              params_hash := md5(
                (query_params - 'cache_ttl')::TEXT
              );

              -- Try cache first if enabled
              IF use_cache THEN
                SELECT tile_data, created_at INTO cached_tile, last_modified
                FROM geometries_tile_cache cache
                WHERE cache.z = get_geoplaces_for_tiles_cached.z
                  AND cache.x = get_geoplaces_for_tiles_cached.x
                  AND cache.y = get_geoplaces_for_tiles_cached.y
                  AND cache.params_hash = params_hash
                  AND cache.created_at > NOW() - (cache_ttl_seconds || 's')::INTERVAL
                LIMIT 1;

                -- Cache hit - update hit counter and return cached tile
                IF FOUND THEN
                  UPDATE geometries_tile_cache cache
                  SET hits = cache.hits + 1
                  WHERE cache.z = get_geoplaces_for_tiles_cached.z
                    AND cache.x = get_geoplaces_for_tiles_cached.x
                    AND cache.y = get_geoplaces_for_tiles_cached.y
                    AND cache.params_hash = params_hash;

                  RETURN cached_tile;
                END IF;
              END IF;

              -- Cache miss or caching disabled - generate new tile
              cached_tile := get_geoplaces_for_tiles(z, x, y, query_params);

              -- Store in cache if enabled and tile generation succeeded
              IF use_cache AND cached_tile IS NOT NULL THEN
                INSERT INTO geometries_tile_cache (z, x, y, params_hash, tile_data)
                VALUES (z, x, y, params_hash, cached_tile)
                ON CONFLICT (z, x, y, params_hash)
                DO UPDATE SET
                  tile_data = EXCLUDED.tile_data,
                  created_at = NOW();
              END IF;

              RETURN cached_tile;
            END;
            $$ LANGUAGE plpgsql STABLE PARALLEL SAFE;

            -- Function to clean up old cache entries
            CREATE OR REPLACE FUNCTION cleanup_tile_cache(older_than_hours INT DEFAULT 24)
            RETURNS INT AS $$
            DECLARE
              deleted_count INT;
            BEGIN
              DELETE FROM geometries_tile_cache
              WHERE created_at < NOW() - (older_than_hours || ' hours')::INTERVAL;

              GET DIAGNOSTICS deleted_count = ROW_COUNT;
              RETURN deleted_count;
            END;
            $$ LANGUAGE plpgsql;

            -- Grant permissions
            GRANT EXECUTE ON FUNCTION get_geoplaces_for_tiles_cached(INT, INT, INT, JSONB) TO PUBLIC;
            GRANT EXECUTE ON FUNCTION cleanup_tile_cache(INT) TO PUBLIC;
            """,
            reverse_sql="""
            -- Remove cached function
            DROP FUNCTION IF EXISTS get_geoplaces_for_tiles_cached(INT, INT, INT, JSONB);
            DROP FUNCTION IF EXISTS cleanup_tile_cache(INT);

            -- Drop cache table
            DROP TABLE IF EXISTS geometries_tile_cache;
            """
        ),
    ]
