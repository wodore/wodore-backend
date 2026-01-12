"""
Management command to import GeoNames hierarchy data.

Downloads and imports GeoNames hierarchy relationships from hierarchy.zip.
The hierarchy file contains parent-child relationships between geonames.

Usage:
    app import_hierarchy                    # Import all hierarchy data
    app import_hierarchy -c alps            # Import for all Alpine countries
    app import_hierarchy -c ch              # Import only for specific countries
    app import_hierarchy --clear            # Clear all hierarchy data first
"""

import urllib.request
import zipfile
import tempfile

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from ...models import GeoName
from ._country_groups import expand_countries


class Command(BaseCommand):
    help = "Import GeoNames hierarchy data"

    # GeoNames hierarchy URL
    HIERARCHY_URL = "https://download.geonames.org/export/dump/hierarchy.zip"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-c",
            "--countries",
            type=str,
            default=None,
            help="Comma-separated country codes or group name (e.g., 'ch,de' or 'alps' for AT,CH,DE,FR,IT,LI,MC,SI). If not specified, imports all.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear all hierarchy data before import",
        )

    def handle(self, *args, **options) -> None:
        countries = None
        if options["countries"]:
            countries = expand_countries(options["countries"])

        clear = options["clear"]

        if countries:
            self.stdout.write(
                f"Importing GeoNames hierarchy for countries: {', '.join(countries)}"
            )
        else:
            self.stdout.write("Importing GeoNames hierarchy for all countries")

        # Clear hierarchy if requested
        if clear:
            self._clear_hierarchy(countries)

        # Import hierarchy data from hierarchy.zip
        imported, skipped = self._import_hierarchy(countries)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nHierarchy file import complete: {imported} relationships imported, {skipped} skipped"
            )
        )

        # Build administrative hierarchy from admin codes
        self.stdout.write("\nBuilding administrative hierarchy from admin codes...")
        admin_linked = self._build_admin_hierarchy(countries)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nAdmin hierarchy complete: {admin_linked} places linked to administrative divisions"
            )
        )

    def _clear_hierarchy(self, countries: list[str] | None) -> None:
        """Clear hierarchy data."""
        if countries:
            for country_code in countries:
                count = (
                    GeoName.objects.filter(country_code=country_code)
                    .exclude(parent__isnull=True)
                    .count()
                )
                if count > 0:
                    GeoName.objects.filter(country_code=country_code).update(
                        parent=None, hierarchy_type=""
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Cleared {count} hierarchy relationships for {country_code}"
                        )
                    )
        else:
            count = GeoName.objects.exclude(parent__isnull=True).count()
            if count > 0:
                confirm = input(
                    f"Are you sure you want to clear ALL {count} hierarchy relationships? Type 'yes' to confirm: "
                )
                if confirm.lower() != "yes":
                    self.stdout.write(self.style.WARNING("Clear cancelled"))
                    raise SystemExit(0)

                GeoName.objects.all().update(parent=None, hierarchy_type="")
                self.stdout.write(
                    self.style.SUCCESS(f"Cleared {count} hierarchy relationships")
                )

    def _import_hierarchy(self, countries: list[str] | None) -> tuple[int, int]:
        """Import hierarchy data from GeoNames hierarchy.zip file."""
        imported_count = 0
        skipped_count = 0

        # Build a set of geoname_ids we care about (for filtering)
        if countries:
            self.stdout.write("Loading GeoName IDs for filtering...")
            geoname_ids = set(
                GeoName.objects.filter(country_code__in=countries).values_list(
                    "geoname_id", flat=True
                )
            )
            self.stdout.write(f"Loaded {len(geoname_ids)} geoname IDs for filtering")
        else:
            geoname_ids = None

        # Download the hierarchy file
        self.stdout.write(f"Downloading hierarchy from: {self.HIERARCHY_URL}")

        try:
            # Download zip file
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".zip"
            ) as tmp_zip:
                try:
                    with urllib.request.urlopen(
                        self.HIERARCHY_URL, timeout=300
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
                    self.stdout.write(f"URL: {self.HIERARCHY_URL}")
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

            self.stdout.write("Extracting hierarchy file...")

            # Extract and process
            import os

            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(tmp_zip_path, "r") as zip_ref:
                    zip_ref.extractall(tmp_dir)

                # Find the .txt file
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

                self.stdout.write("Processing hierarchy relationships...")

                # Collect all updates in memory first, then batch update
                updates = []
                batch_size = 1000

                with open(txt_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        try:
                            parts = line.strip().split("\t")
                            if len(parts) < 3:
                                continue

                            parent_id = int(parts[0])
                            child_id = int(parts[1])
                            hierarchy_type = parts[2]

                            # Filter by country if specified
                            if geoname_ids is not None:
                                if child_id not in geoname_ids:
                                    skipped_count += 1
                                    continue

                            # Collect update
                            updates.append(
                                {
                                    "child_id": child_id,
                                    "parent_id": parent_id,
                                    "hierarchy_type": hierarchy_type,
                                }
                            )

                            # Process batch
                            if len(updates) >= batch_size:
                                self._process_batch(updates)
                                imported_count += len(updates)
                                updates = []

                                if imported_count % 10000 == 0:
                                    self.stdout.write(
                                        f"  Processed {imported_count} relationships..."
                                    )

                        except Exception as e:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Error processing line {line_num}: {e}"
                                )
                            )
                            continue

                # Process remaining updates
                if updates:
                    self._process_batch(updates)
                    imported_count += len(updates)

            # Clean up zip file
            os.unlink(tmp_zip_path)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error downloading/processing hierarchy: {e}")
            )
            import traceback

            traceback.print_exc()

        return imported_count, skipped_count

    def _process_batch(self, updates: list[dict]) -> None:
        """Process a batch of hierarchy updates."""
        # Collect all parent IDs to check if they exist
        parent_ids = [u["parent_id"] for u in updates]
        existing_parents = set(
            GeoName.objects.filter(geoname_id__in=parent_ids).values_list(
                "geoname_id", flat=True
            )
        )

        with transaction.atomic():
            for update in updates:
                # Only update if parent exists in our database
                if update["parent_id"] in existing_parents:
                    GeoName.objects.filter(geoname_id=update["child_id"]).update(
                        parent_id=update["parent_id"],
                        hierarchy_type=update["hierarchy_type"],
                    )

    def _build_admin_hierarchy(self, countries: list[str] | None) -> int:
        """
        Build administrative hierarchy relationships using admin codes.

        Links places (cities, mountains, lakes, etc.) to their administrative
        divisions (ADM3, ADM2, ADM1) based on admin1_code, admin2_code, admin3_code.
        """
        linked_count = 0

        # Build query for places to link
        query = GeoName.objects.exclude(
            feature__feature_code__in=[
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
        )

        if countries:
            query = query.filter(country_code__in=countries)

        # Only link places that don't already have a parent from hierarchy.zip
        query = query.filter(parent__isnull=True)

        # Build a lookup dictionary: country_code + admin codes -> geoname_id
        self.stdout.write("Building administrative division lookup...")

        admin_lookup = {}

        # Get all administrative divisions
        admin_divisions = GeoName.objects.filter(
            feature__feature_code__in=["ADM1", "ADM2", "ADM3", "ADM4"]
        )

        if countries:
            admin_divisions = admin_divisions.filter(country_code__in=countries)

        for adm in admin_divisions.values(
            "geoname_id",
            "country_code",
            "admin1_code",
            "admin2_code",
            "admin3_code",
            "admin4_code",
            "feature__feature_code",
        ):
            country = adm["country_code"]
            feature_code = adm["feature__feature_code"]

            # Build keys for different admin levels
            # ADM1: country + admin1
            if feature_code == "ADM1" and adm["admin1_code"]:
                key = f"{country}|{adm['admin1_code']}"
                if key not in admin_lookup:
                    admin_lookup[key] = {"adm1": adm["geoname_id"]}

            # ADM2: country + admin1 + admin2
            if feature_code == "ADM2" and adm["admin1_code"] and adm["admin2_code"]:
                key = f"{country}|{adm['admin1_code']}|{adm['admin2_code']}"
                if key not in admin_lookup:
                    admin_lookup[key] = {"adm2": adm["geoname_id"]}

            # ADM3: country + admin1 + admin2 + admin3
            if (
                feature_code == "ADM3"
                and adm["admin1_code"]
                and adm["admin2_code"]
                and adm["admin3_code"]
            ):
                key = f"{country}|{adm['admin1_code']}|{adm['admin2_code']}|{adm['admin3_code']}"
                if key not in admin_lookup:
                    admin_lookup[key] = {"adm3": adm["geoname_id"]}

            # ADM4: country + admin1 + admin2 + admin3 + admin4
            if (
                feature_code == "ADM4"
                and adm["admin1_code"]
                and adm["admin2_code"]
                and adm["admin3_code"]
                and adm["admin4_code"]
            ):
                key = f"{country}|{adm['admin1_code']}|{adm['admin2_code']}|{adm['admin3_code']}|{adm['admin4_code']}"
                if key not in admin_lookup:
                    admin_lookup[key] = {"adm4": adm["geoname_id"]}

        self.stdout.write(
            f"Built lookup with {len(admin_lookup)} administrative divisions"
        )
        self.stdout.write("Linking places to administrative divisions...")

        # Process places in batches
        batch_size = 1000
        total_places = query.count()
        processed = 0

        for place in query.iterator(chunk_size=batch_size):
            parent_id = None

            # Try to find most specific admin division
            # Priority: ADM4 > ADM3 > ADM2 > ADM1

            if (
                place.admin4_code
                and place.admin3_code
                and place.admin2_code
                and place.admin1_code
            ):
                key = f"{place.country_code}|{place.admin1_code}|{place.admin2_code}|{place.admin3_code}|{place.admin4_code}"
                if key in admin_lookup and "adm4" in admin_lookup[key]:
                    parent_id = admin_lookup[key]["adm4"]

            if (
                not parent_id
                and place.admin3_code
                and place.admin2_code
                and place.admin1_code
            ):
                key = f"{place.country_code}|{place.admin1_code}|{place.admin2_code}|{place.admin3_code}"
                if key in admin_lookup and "adm3" in admin_lookup[key]:
                    parent_id = admin_lookup[key]["adm3"]

            if not parent_id and place.admin2_code and place.admin1_code:
                key = f"{place.country_code}|{place.admin1_code}|{place.admin2_code}"
                if key in admin_lookup and "adm2" in admin_lookup[key]:
                    parent_id = admin_lookup[key]["adm2"]

            if not parent_id and place.admin1_code:
                key = f"{place.country_code}|{place.admin1_code}"
                if key in admin_lookup and "adm1" in admin_lookup[key]:
                    parent_id = admin_lookup[key]["adm1"]

            # Update if we found a parent
            if parent_id:
                place.parent_id = parent_id
                place.hierarchy_type = "ADM"
                place.save(update_fields=["parent_id", "hierarchy_type"])
                linked_count += 1

            processed += 1
            if processed % 1000 == 0:
                self.stdout.write(
                    f"  Processed {processed}/{total_places} places, linked {linked_count}..."
                )

        return linked_count
