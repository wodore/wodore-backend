from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.conf import settings
import os
from pathlib import Path
import subprocess


class Command(BaseCommand):
    help = "Generate PMTiles for static/unmodified POIs using martin (requires local martin installation)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-zoom",
            type=int,
            default=14,
            help="Maximum zoom level to generate (default: 14)",
        )
        parser.add_argument(
            "--min-zoom",
            type=int,
            default=0,
            help="Minimum zoom level to generate (default: 0)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Output directory for PMTiles file (default: ./martin_sync/pmtiles/)",
        )
        parser.add_argument(
            "--name",
            type=str,
            default="static_pois",
            help="Name for the generated PMTiles file without extension (default: static_pois)",
        )
        parser.add_argument(
            "--function",
            type=str,
            default="get_static_geoplaces_for_tiles",
            help="PostgreSQL function name to use for tile generation (default: get_static_geoplaces_for_tiles)",
        )
        parser.add_argument(
            "--url-query",
            type=str,
            default="",
            help="URL query parameters for Martin source (e.g., clustering params)",
        )

    def handle(self, *args, **options):
        max_zoom = options["max_zoom"]
        min_zoom = options["min_zoom"]
        output_dir = options["output_dir"]
        name = options["name"]
        function_name = options["function"]
        url_query = options["url_query"]

        # Default output directory
        if output_dir is None:
            output_dir = "./martin_sync/pmtiles"

        output_path = os.path.join(output_dir, f"{name}.pmtiles")

        self.stdout.write(
            self.style.SUCCESS(
                "Starting PMTiles generation for static POIs using martin..."
            )
        )

        # Check if martin is available locally
        martin_version = self._check_martin_installed()
        if not martin_version:
            raise CommandError(
                "martin command not found. Please install martin locally.\n"
                "See https://maplibre.org/martin/installation/ for installation instructions.\n"
                "Quick install:\n"
                "  Ubuntu/Debian: wget https://github.com/maplibre/martin/releases/download/v1.4.0/debian-x86_64.deb && dpkg -i debian-x86_64.deb\n"
                "  Alpine: wget https://github.com/maplibre/martin/releases/download/v1.4.0/martin-x86_64-unknown-linux-musl.tar.gz && tar -xzf martin-x86_64-unknown-linux-musl.tar.gz -C /usr/local/bin martin\n"
                "  macOS: brew install martin"
            )

        self.stdout.write(self.style.SUCCESS(f"Using martin version: {martin_version}"))

        # Create a new PostGIS function for static POIs only
        self._create_static_pois_function(function_name)

        # Create output directory if needed
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate PMTiles directly using martin
        success = self._generate_pmtiles(
            function_name, min_zoom, max_zoom, url_query, output_path
        )

        if not success:
            raise CommandError("Failed to generate PMTiles")

        self.stdout.write(
            self.style.SUCCESS(f"PMTiles generation complete: {output_path}")
        )

    def _check_martin_installed(self):
        """Check if martin command is available locally"""
        try:
            result = subprocess.run(
                ["martin", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Extract version from output like "martin 1.4.0"
                version = result.stdout.strip().split()[-1]
                return version
            return None
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ):
            return None

    def _create_static_pois_function(
        self, function_name="get_static_geoplaces_for_tiles"
    ):
        """Create a PostGIS function for static POIs only (unmodified)"""
        self.stdout.write(
            f"Creating PostGIS function '{function_name}' for static POIs..."
        )

        # This function will be used by Martin to generate tiles
        function_sql = f"""
        CREATE OR REPLACE FUNCTION {function_name}(
            tile_bbox_4326 geometry,
            zoom_level integer DEFAULT NULL,
            tile_hash integer DEFAULT NULL
        )
        RETURNS TABLE(
            id integer,
            slug character varying,
            geometry geometry,
            name character varying,
            i18n jsonb,
            importance smallint,
            elevation integer,
            country_code character varying(2),
            detail_type character varying(20),
            categories integer[],
            cluster_ref_zoom integer
        ) AS $$
        BEGIN
            RETURN QUERY
            WITH
            -- Only include static (unmodified) POIs
            static_pois AS (
                SELECT
                    gp.id, gp.slug, gp.location, gp.importance,
                    gp.elevation, gp.country_code, gp.detail_type, gp.extra,
                    gp.name, gp.i18n,
                    ARRAY_AGG(DISTINCT gc.category_id) as categories
                FROM geometries_geoplace gp
                LEFT JOIN geometries_geoplace_category gc ON gp.id = gc.geo_place_id
                WHERE gp.is_public = true
                    AND gp.is_active = true
                    AND gp.is_modified = false  -- Only static POIs
                    AND gp.location && tile_bbox_4326
                    AND ST_Intersects(gp.location, tile_bbox_4326)
                GROUP BY gp.id, gp.slug, gp.location, gp.name, gp.i18n, gp.importance,
                         gp.elevation, gp.country_code, gp.detail_type, gp.extra
            ),
            geo_places_with_categories AS (
                SELECT
                    sp.id, sp.slug, sp.location, sp.name, sp.i18n,
                    sp.importance, sp.elevation, sp.country_code, sp.detail_type,
                    sp.categories, 8 as cluster_ref_zoom
                FROM static_pois sp
            )
            SELECT
                gpwc.id, gpwc.slug, gpwc.location, gpwc.name, gpwc.i18n,
                gpwc.importance, gpwc.elevation, gpwc.country_code, gpwc.detail_type,
                gpwc.categories, gpwc.cluster_ref_zoom
            FROM geo_places_with_categories gpwc;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
        """

        with connection.cursor() as cursor:
            cursor.execute(function_sql)

        self.stdout.write(
            self.style.SUCCESS(f"Created static POIs function '{function_name}'")
        )

    def _get_db_url(self):
        """Get PostgreSQL connection URL from Django settings"""
        db_settings = settings.DATABASES["default"]
        return f"postgresql://{db_settings['USER']}:{db_settings['PASSWORD']}@{db_settings['HOST']}:{db_settings['PORT']}/{db_settings['NAME']}"

    def _generate_pmtiles(
        self, function_name, min_zoom, max_zoom, url_query, output_path
    ):
        """Generate PMTiles directly using martin command"""
        self.stdout.write(
            f"Generating PMTiles (zoom {min_zoom}-{max_zoom}) using martin..."
        )

        db_url = self._get_db_url()

        # Build martin cp command
        cmd = [
            "martin",
            "cp",
            "--source",
            f"pg:{function_name}",
            "--output-file",
            output_path,
            "--min-zoom",
            str(min_zoom),
            "--max-zoom",
            str(max_zoom),
            "--bbox",
            "-180,-85.05112877980659,180,85.0511287798066",
            "--concurrency",
            "4",
            db_url,
        ]

        if url_query:
            cmd.extend(["--url-query", url_query])

        self.stdout.write("Running martin cp (this may take a while)...")

        try:
            # Run martin cp
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200,  # 2 hour timeout for large tilesets
            )

            if result.returncode != 0:
                self.stdout.write(
                    self.style.ERROR(f"martin cp failed: {result.stderr}")
                )
                return False

            # Check if file was created
            if os.path.exists(output_path):
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created PMTiles file: {output_path} ({size_mb:.2f} MB)"
                    )
                )
                return True
            else:
                self.stdout.write(self.style.ERROR("PMTiles file was not created"))
                return False

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"martin cp failed: {e}"))
            return False
        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR("martin cp timed out"))
            return False
