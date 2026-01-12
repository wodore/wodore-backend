"""
Management command to import GeoNames administrative boundaries.

Downloads and imports GeoNames boundary data (shapes) from GeoJSON format.
Processes shapes_simplified_low.json for country boundaries.

Usage:
    app import_boundaries                          # Import all countries
    app import_boundaries -c alps                  # Import all Alpine countries
    app import_boundaries -c ch,de,fr,it,at,li    # Import specific countries
    app import_boundaries -c ch --drop             # Drop CH data first
    app import_boundaries --drop-all               # Drop all data first
    app import_boundaries --admin-level 1          # Import only ADM1 (states/provinces)
"""

import json
import urllib.request

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from ...models import Boundary, GeoName
from ._country_groups import expand_countries


class Command(BaseCommand):
    help = "Import GeoNames administrative boundaries from GeoJSON"

    # GeoNames shapes URL (tab-separated: geonameId, geoJson)
    SHAPES_URL = "https://download.geonames.org/export/dump/shapes_all_low.zip"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-c",
            "--countries",
            type=str,
            default=None,
            help="Comma-separated country codes or group name (e.g., 'ch,de' or 'alps' for AT,CH,DE,FR,IT,LI,MC,SI). If not specified, imports all.",
        )
        parser.add_argument(
            "--drop",
            action="store_true",
            help="Drop existing data for specified countries before import",
        )
        parser.add_argument(
            "--drop-all",
            action="store_true",
            help="Drop all boundary data before import (use with caution!)",
        )
        parser.add_argument(
            "--admin-level",
            type=int,
            choices=[0, 1, 2, 3, 4],
            default=None,
            help="Import only specific admin level (0=country, 1-4=subdivisions)",
        )

    def handle(self, *args, **options) -> None:
        countries = None
        if options["countries"]:
            countries = expand_countries(options["countries"])

        drop = options["drop"]
        drop_all = options["drop_all"]
        admin_level_filter = options["admin_level"]

        if countries:
            self.stdout.write(
                f"Importing GeoNames boundaries for countries: {', '.join(countries)}"
            )
        else:
            self.stdout.write("Importing GeoNames boundaries for all countries")

        # Handle drop operations
        if drop_all:
            self._drop_all()
        elif drop and countries:
            self._drop_countries(countries)

        # Import boundary data
        created, updated = self._import_boundaries(countries, admin_level_filter)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nBoundary import complete: {created} created, {updated} updated"
            )
        )

    def _drop_all(self) -> None:
        """Drop all Boundary data."""
        count = Boundary.objects.count()
        if count == 0:
            self.stdout.write("No data to drop")
            return

        confirm = input(
            f"Are you sure you want to delete ALL {count} boundary records? Type 'yes' to confirm: "
        )
        if confirm.lower() != "yes":
            self.stdout.write(self.style.WARNING("Drop cancelled"))
            raise SystemExit(0)

        Boundary.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Dropped {count} records"))

    def _drop_countries(self, countries: list[str]) -> None:
        """Drop Boundary data for specified countries."""
        for country_code in countries:
            count = Boundary.objects.filter(country_code=country_code).count()
            if count > 0:
                Boundary.objects.filter(country_code=country_code).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Dropped {count} records for {country_code}")
                )

    def _import_boundaries(
        self, countries: list[str] | None, admin_level_filter: int | None
    ) -> tuple[int, int]:
        """Import boundary data from GeoNames shapes file."""
        created_count = 0
        updated_count = 0

        # Pre-load GeoName data into memory for faster lookups
        self.stdout.write("Loading GeoName data for lookups...")
        geoname_lookup = {}

        # Build query to fetch relevant geonames
        query = GeoName.objects.all()
        if countries:
            query = query.filter(country_code__in=countries)

        # Only fetch administrative features
        admin_features = [
            "ADM1",
            "ADM2",
            "ADM3",
            "ADM4",
            "ADM5",
            "ADMD",
            "PCL",
            "PCLD",
            "PCLF",
            "PCLI",
            "PCLIX",
            "PCLS",
        ]
        query = query.filter(feature__feature_code__in=admin_features)

        for geoname in query.values(
            "geoname_id", "name", "country_code", "feature__feature_code"
        ):
            geoname_lookup[geoname["geoname_id"]] = {
                "name": geoname["name"],
                "country_code": geoname["country_code"],
                "feature_code": geoname["feature__feature_code"],
            }

        self.stdout.write(f"Loaded {len(geoname_lookup)} geoname records for lookup")

        # Download the shapes file
        self.stdout.write(f"Downloading boundaries from: {self.SHAPES_URL}")

        import tempfile
        import zipfile
        import os

        try:
            # Download zip file
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".zip"
            ) as tmp_zip:
                try:
                    with urllib.request.urlopen(
                        self.SHAPES_URL, timeout=300
                    ) as response:
                        # Get file size if available
                        file_size = response.headers.get("Content-Length")
                        if file_size:
                            file_size = int(file_size)
                            self.stdout.write(
                                f"File size: {file_size / (1024 * 1024):.2f} MB"
                            )

                        downloaded = 0
                        chunk_size = 8192
                        while chunk := response.read(chunk_size):
                            tmp_zip.write(chunk)
                            downloaded += len(chunk)

                            # Show progress every 1 MB
                            if downloaded % (1024 * 1024) == 0:
                                self.stdout.write(
                                    f"  Downloaded {downloaded / (1024 * 1024):.1f} MB..."
                                )

                        self.stdout.write(
                            f"Download complete: {downloaded / (1024 * 1024):.2f} MB"
                        )

                except urllib.error.HTTPError as e:
                    self.stdout.write(
                        self.style.ERROR(f"HTTP Error {e.code}: {e.reason}")
                    )
                    self.stdout.write(f"URL: {self.SHAPES_URL}")
                    return 0, 0
                except urllib.error.URLError as e:
                    self.stdout.write(self.style.ERROR(f"Network error: {e.reason}"))
                    self.stdout.write(
                        "Please check your internet connection and try again."
                    )
                    return 0, 0
                except TimeoutError:
                    self.stdout.write(
                        self.style.ERROR("Download timeout after 5 minutes")
                    )
                    self.stdout.write(
                        "Please try again later or check your connection."
                    )
                    return 0, 0

                tmp_zip_path = tmp_zip.name

            self.stdout.write("Extracting shapes file...")

            # Extract and process
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(tmp_zip_path, "r") as zip_ref:
                    zip_ref.extractall(tmp_dir)

                # Find the .txt file
                import os

                txt_file = None
                for file in os.listdir(tmp_dir):
                    if file.endswith(".txt"):
                        txt_file = os.path.join(tmp_dir, file)
                        break

                if not txt_file:
                    self.stdout.write(
                        self.style.ERROR("Could not find .txt file in zip archive")
                    )
                    return 0, 0

                self.stdout.write("Processing boundaries...")

                # Process each line
                total_lines = 0
                matched_lines = 0
                with open(txt_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            # Skip header line
                            if line_num == 1 and line.startswith("geoNameId"):
                                continue

                            parts = line.strip().split("\t")
                            if len(parts) < 2:
                                continue

                            total_lines += 1
                            geoname_id = int(parts[0])
                            geojson_str = parts[1]

                            # Parse GeoJSON
                            geojson = json.loads(geojson_str)

                            # Look up geoname data from our pre-loaded lookup table
                            geoname_data = geoname_lookup.get(geoname_id)
                            if not geoname_data:
                                # Skip if we don't have this geoname (not in our filtered set)
                                continue

                            matched_lines += 1

                            name = geoname_data["name"]
                            country_code = geoname_data["country_code"]
                            feature_code = geoname_data["feature_code"]

                            # Determine admin level from feature code
                            admin_level = None
                            if feature_code in [
                                "PCL",
                                "PCLD",
                                "PCLF",
                                "PCLI",
                                "PCLIX",
                                "PCLS",
                            ]:
                                admin_level = 0
                            elif feature_code == "ADM1":
                                admin_level = 1
                            elif feature_code == "ADM2":
                                admin_level = 2
                            elif feature_code == "ADM3":
                                admin_level = 3
                            elif feature_code in ["ADM4", "ADM5"]:
                                admin_level = 4
                            elif feature_code == "ADMD":
                                admin_level = None  # Administrative division (generic)

                            # Filter by admin level if specified
                            if (
                                admin_level_filter is not None
                                and admin_level != admin_level_filter
                            ):
                                continue

                            # Create geometry
                            geos_geom = GEOSGeometry(json.dumps(geojson), srid=4326)

                            # Ensure MultiPolygon
                            if geos_geom.geom_type == "Polygon":
                                geos_geom = MultiPolygon(geos_geom)
                            elif geos_geom.geom_type != "MultiPolygon":
                                # Skip non-polygon geometries
                                continue

                            # Create or update
                            with transaction.atomic():
                                boundary, created = Boundary.objects.update_or_create(
                                    geoname_id=geoname_id,
                                    defaults={
                                        "name": name,
                                        "feature_code": feature_code,
                                        "geometry": geos_geom,
                                        "country_code": country_code,
                                        "admin_level": admin_level,
                                    },
                                )

                            if created:
                                created_count += 1
                            else:
                                updated_count += 1

                            if (created_count + updated_count) % 100 == 0:
                                self.stdout.write(
                                    f"  Processed {created_count + updated_count} boundaries..."
                                )

                        except Exception as e:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Error processing line {line_num}: {e}"
                                )
                            )
                            continue

            # Clean up zip file
            os.unlink(tmp_zip_path)

            # Print statistics
            self.stdout.write("\nStatistics:")
            self.stdout.write(f"  Total shapes in file: {total_lines}")
            self.stdout.write(f"  Matched to our geonames: {matched_lines}")
            self.stdout.write(
                f"  Successfully imported: {created_count + updated_count}"
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error downloading/processing boundaries: {e}")
            )
            import traceback

            traceback.print_exc()

        return created_count, updated_count
