# Tile Server Examples

This directory contains example scripts and utilities for working with the Martin tile server and geospatial data.

## Import Ski Routes Script

`import_skiroutes.py` - Import ski routes from SQLite/GeoPackage files to PostGIS for serving via Martin tile server.

### Usage

```bash
python tile_server/examples/import_skiroutes.py <path/to/routes.sqlite> [table_name]
```

### Arguments

- `sqlite_file` (required): Path to the SQLite or GeoPackage file containing route data
- `table_name` (optional): Destination table name in PostGIS (default: `test_ski_routes`)

### Examples

Import the Alps ski routes:
```bash
python tile_server/examples/import_skiroutes.py tile_server/tests/Alps.sqlite test_ski_routes
```

Use default table name:
```bash
python tile_server/examples/import_skiroutes.py tile_server/tests/Alps.sqlite
```

### What the script does

1. **Drops existing table** (if it exists) to ensure clean import
2. **Imports data** from SQLite to PostGIS using ogr2ogr
3. **Transforms coordinates** from Web Mercator (SRID 900914) to WGS84 (SRID 4326)
4. **Creates spatial index** for fast queries
5. **Verifies the import** with statistics and bounding box

### Requirements

- Docker and docker-compose (for PostgreSQL/PostGIS access)
- ogr2ogr (part of GDAL tools)
- SQLite/GeoPackage file with geometry data

### After import

Once the import is complete, you'll need to:

1. **Add the table to Martin configuration** (`tile_server/config/martin.yaml`):

```yaml
tables:
  your_table_name:
    layer_id: your_layer_name
    schema: public
    table: your_table_name
    geometry_column: geometry
    srid: 4326
    geometry_type: LINESTRING
    properties:
      id: int4
      start: text
      stop: text
      # ... add other properties as needed
    minzoom: 0
    maxzoom: 14
```

2. **Restart Martin**:
```bash
docker compose restart martin
```

3. **Test the tiles**:
```bash
curl http://localhost:8075/your_table_name/8/133/90 -o test.pbf
ls -lh test.pbf
```

### Data source example

The script was tested with Swiss Alps ski tour data in SQLite format, containing:
- 13,000+ routes
- LineString geometries
- Properties: start point, end point, difficulty, length, etc.

### Troubleshooting

**Error: "File not found"**
- Check the path to your SQLite file
- Use absolute paths if relative paths don't work

**Error: "docker: command not found"**
- Ensure Docker is installed and running
- Check that the PostgreSQL container is named `django-local-postgis`

**Empty tiles after import**
- Check the SRID of your source data
- Verify geometry column name matches your data
- Test with different zoom levels

**ogr2ogr errors**
- Install GDAL tools: `sudo apt install gdal-bin`
- Check that your SQLite file is valid
- Ensure the file contains spatial data (geometry columns)
