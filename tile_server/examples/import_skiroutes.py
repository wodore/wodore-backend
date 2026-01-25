#!/usr/bin/env python3
"""
Import ski routes from SQLite/GeoPackage file to PostGIS.

This script imports ski route data from a SQLite file into the PostgreSQL/PostGIS database,
transforms coordinates to WGS84, and creates necessary indexes.

Usage:
    python tile_server/examples/import_skiroutes.py path/to/routes.sqlite [table_name]

Example:
    python tile_server/examples/import_skiroutes.py tile_server/tests/Alps.sqlite test_ski_routes
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description=""):
    """Run a shell command and handle errors."""
    print(f"\n{'=' * 60}")
    print(f"{description}")
    print(f"Command: {cmd}")
    print(f"{'=' * 60}")

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        sys.exit(1)
    else:
        print("✅ Success")
        if result.stdout:
            print(result.stdout)
    return result


def import_ski_routes(sqlite_path, table_name="test_ski_routes"):
    """
    Import ski routes from SQLite to PostGIS.

    Args:
        sqlite_path: Path to the SQLite/GeoPackage file
        table_name: Name for the destination table in PostGIS
    """
    sqlite_path = Path(sqlite_path).resolve()

    if not sqlite_path.exists():
        print(f"❌ Error: File not found: {sqlite_path}")
        sys.exit(1)

    # Database connection parameters (adjust as needed)
    db_params = {
        "host": "localhost",
        "port": "5432",
        "user": "wodore",
        "password": "wodore",
        "dbname": "wodore",
    }

    pg_conn = (
        f'PG:"host={db_params["host"]} '
        f"user={db_params['user']} "
        f"password={db_params['password']} "
        f"dbname={db_params['dbname']} "
        f'port={db_params["port"]}"'
    )

    print(f"\n{'#' * 60}")
    print("# Importing ski routes from SQLite to PostGIS")
    print(f"# Source: {sqlite_path}")
    print(f"# Target table: {table_name}")
    print(f"{'#' * 60}")

    # Step 1: Drop existing table if it exists
    drop_sql = f"DROP TABLE IF EXISTS {table_name};"
    run_command(
        f'docker exec django-local-postgis psql -U {db_params["user"]} -d {db_params["dbname"]} -c "{drop_sql}"',
        f"Step 1: Dropping existing table {table_name} (if exists)",
    )

    # Step 2: Import SQLite to PostGIS using ogr2ogr
    run_command(
        f'ogr2ogr -f "PostgreSQL" {pg_conn} {sqlite_path} '
        f"-lco GEOMETRY_NAME=geometry -nln {table_name} -overwrite",
        f"Step 2: Importing data from {sqlite_path.name} to {table_name}",
    )

    # Step 3: Transform geometry from Web Mercator (SRID 900914) to WGS84 (SRID 4326)
    transform_sql = f"""
        -- Add a temporary column for transformed geometry
        ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS geometry_wgs84 geometry(LineString,4326);

        -- Transform the geometry from source SRID to 4326 (WGS84)
        -- ogr2ogr typically imports to Web Mercator (900914) or similar
        UPDATE {table_name} SET geometry_wgs84 = ST_Transform(geometry, 4326);

        -- Drop the old geometry column and rename the new one
        ALTER TABLE {table_name} DROP COLUMN geometry;
        ALTER TABLE {table_name} RENAME COLUMN geometry_wgs84 TO geometry;

        -- Create a GiST index on the geometry for fast spatial queries
        CREATE INDEX IF NOT EXISTS {table_name}_geometry_geom_idx
        ON {table_name} USING gist (geometry);
    """

    # Run the transformation SQL
    run_command(
        f'docker exec django-local-postgis psql -U {db_params["user"]} -d {db_params["dbname"]} -c "{transform_sql}"',
        "Step 3: Transforming geometry to WGS84 (SRID 4326) and creating spatial index",
    )

    # Step 4: Verify the import
    verify_sql = f"""
        SELECT
            COUNT(*) as total_routes,
            ST_SRID(geometry) as srid,
            ST_AsText(ST_Centroid(geometry)) as sample_centroid
        FROM {table_name};
    """

    run_command(
        f'docker exec django-local-postgis psql -U {db_params["user"]} -d {db_params["dbname"]} -c "{verify_sql}"',
        "Step 4: Verifying import",
    )

    # Step 5: Show table structure
    run_command(
        f'docker exec django-local-postgis psql -U {db_params["user"]} -d {db_params["dbname"]} -c "\\d {table_name}"',
        "Step 5: Table structure",
    )

    # Step 6: Show bounding box
    bbox_sql = f"""
        SELECT
            'Bounding Box:' as info,
            ST_XMin(ST_Extent(geometry))::text || ', ' ||
            ST_YMin(ST_Extent(geometry))::text as min_lon_lat,
            ST_XMax(ST_Extent(geometry))::text || ', ' ||
            ST_YMax(ST_Extent(geometry))::text as max_lon_lat
        FROM {table_name};
    """

    run_command(
        f'docker exec django-local-postgis psql -U {db_params["user"]} -d {db_params["dbname"]} -c "{bbox_sql}"',
        "Step 6: Bounding box",
    )

    print(f"\n{'=' * 60}")
    print("✅ Import completed successfully!")
    print(f"{'=' * 60}")
    print(f"\nTable '{table_name}' is now ready for use in Martin tile server.")
    print("\nNext steps:")
    print("1. Add table to tile_server/config/martin.yaml")
    print("2. Restart Martin: docker compose restart martin")
    print(f"3. Test tiles: curl http://localhost:8075/{table_name}/8/133/90")
    print("\nExample Martin configuration:")
    print(f"""
    {table_name}:
      layer_id: {table_name}
      schema: public
      table: {table_name}
      geometry_column: geometry
      srid: 4326
      geometry_type: LINESTRING
      properties:
        id: int4
        start: text
        stop: text
        diff: int4
        length: float8
      minzoom: 0
      maxzoom: 14
    """)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import ski routes from SQLite to PostGIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "sqlite_file", help="Path to SQLite/GeoPackage file containing ski routes"
    )

    parser.add_argument(
        "table_name",
        nargs="?",
        default="test_ski_routes",
        help="Destination table name in PostGIS (default: test_ski_routes)",
    )

    args = parser.parse_args()

    import_ski_routes(args.sqlite_file, args.table_name)


if __name__ == "__main__":
    main()
