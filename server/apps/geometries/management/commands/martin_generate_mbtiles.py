from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pathlib import Path
import os
import subprocess


class Command(BaseCommand):
    help = "Generate MBTiles from Martin config sources using martin cp"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="geoplaces_view",
            help="Martin source name from config (default: geoplaces_view)",
        )
        parser.add_argument(
            "--config",
            type=str,
            default="martin_sync/config/martin.yaml",
            help="Path to Martin config file (default: martin_sync/config/martin.yaml)",
        )
        parser.add_argument(
            "--max-zoom",
            type=int,
            default=14,
            help="Maximum zoom level to generate (default: 14)",
        )
        parser.add_argument(
            "--min-zoom",
            type=int,
            default=5,
            help="Minimum zoom level to generate (default: 5)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Output directory for MBTiles file (default: ./martin_sync/mbtiles/)",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Name for the generated MBTiles file without extension (default: same as source)",
        )
        parser.add_argument(
            "--url-query",
            type=str,
            default="",
            help="URL query parameters for function-based sources (e.g., clustering params)",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=4,
            help="Number of concurrent connections (default: 4)",
        )

    def handle(self, *args, **options):
        source = options["source"]
        config = options["config"]
        max_zoom = options["max_zoom"]
        min_zoom = options["min_zoom"]
        output_dir = options["output_dir"] or "./martin_sync/mbtiles"
        name = options["name"] or source
        url_query = options["url_query"]
        concurrency = options["concurrency"]

        output_path = os.path.join(output_dir, f"{name}.mbtiles")

        self.stdout.write(
            f"Generating MBTiles for source '{source}' (zoom {min_zoom}-{max_zoom})..."
        )

        # Check if martin is available
        martin_version = self._check_martin_installed()
        if not martin_version:
            raise CommandError(
                "martin command not found. Please install martin locally.\n"
                "See https://maplibre.org/martin/installation/ for installation instructions."
            )

        self.stdout.write(f"Using martin version: {martin_version}")

        # Verify config file exists
        if not os.path.exists(config):
            raise CommandError(f"Martin config file not found: {config}")

        # Create output directory if needed
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate MBTiles using martin cp
        success = self._generate_mbtiles(
            config, source, min_zoom, max_zoom, url_query, concurrency, output_path
        )

        if not success:
            raise CommandError("Failed to generate MBTiles")

        self.stdout.write(
            self.style.SUCCESS(f"MBTiles generation complete: {output_path}")
        )

    def _check_martin_installed(self):
        try:
            result = subprocess.run(
                ["martin-cp", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip().split()[-1]
            return None
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ):
            return None

    def _get_db_url(self):
        """Get PostgreSQL connection URL from Django settings."""
        db = settings.DATABASES["default"]
        return f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT']}/{db['NAME']}"

    def _generate_mbtiles(
        self, config, source, min_zoom, max_zoom, url_query, concurrency, output_path
    ):
        db_url = self._get_db_url()
        cmd = [
            "martin-cp",
            "-c",
            config,
            "-s",
            source,
            "-o",
            output_path,
            "--min-zoom",
            str(min_zoom),
            "--max-zoom",
            str(max_zoom),
            "--concurrency",
            str(concurrency),
        ]

        if url_query:
            cmd.extend(["--url-query", url_query])

        self.stdout.write(f"Running: {' '.join(cmd)}")
        self.stdout.write("Running martin-cp (this may take a while)...")

        # Set env vars so martin-cp can resolve them from the config
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        env["MARTIN_SYNC_MOUNT"] = os.path.abspath("./martin_sync")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200,
                env=env,
            )

            if result.returncode != 0:
                self.stdout.write(
                    self.style.ERROR(f"martin cp failed:\n{result.stderr}")
                )
                return False

            if os.path.exists(output_path):
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                self.stdout.write(
                    f"Created MBTiles file: {output_path} ({size_mb:.2f} MB)"
                )
                return True
            else:
                self.stdout.write(self.style.ERROR("MBTiles file was not created"))
                return False

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR("martin cp timed out"))
            return False
