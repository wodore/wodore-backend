"""
Management command to import GeoNames place data.

Downloads and imports GeoNames data for specified countries.
Processes allCountries.txt data and enriches with alternate names.

Usage:
    app import_geonames -c alps                         # Import for all Alpine countries
    app import_geonames -c ch,de,fr,it,at,li           # Import for specific countries
    app import_geonames -c ch --drop                    # Drop CH data first
    app import_geonames -c ch,de --drop-all             # Drop all data first
    app import_geonames -c ch --limit 1000              # Import max 1000 entries
"""

import csv
import os
import tempfile
import urllib.request
import zipfile
from datetime import datetime

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from ...models import AlternativeName, GeoName
from ._country_groups import expand_countries


class Command(BaseCommand):
    help = "Import GeoNames place data for specified countries"

    BASE_URL = "https://download.geonames.org/export/dump/"
    ALTNAMES_URL = "https://download.geonames.org/export/dump/alternatenames/"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-c",
            "--countries",
            type=str,
            required=True,
            help="Comma-separated country codes or group name (e.g., 'ch,de' or 'alps' for AT,CH,DE,FR,IT,LI,MC,SI)",
        )
        parser.add_argument(
            "--drop",
            action="store_true",
            help="Drop existing data for specified countries before import",
        )
        parser.add_argument(
            "-a",
            "--drop-all",
            action="store_true",
            help="Drop all data before import (use with caution!)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of places to import (for testing)",
        )
        parser.add_argument(
            "--skip-altnames",
            action="store_true",
            help="Skip importing alternate names (faster for testing)",
        )

    def handle(self, *args, **options) -> None:
        countries = expand_countries(options["countries"])
        drop = options["drop"]
        drop_all = options["drop_all"]
        limit = options["limit"]
        skip_altnames = options["skip_altnames"]

        self.stdout.write(
            f"Importing GeoNames data for countries: {', '.join(countries)}"
        )

        # Handle drop operations
        if drop_all:
            self._drop_all()
        elif drop:
            self._drop_countries(countries)

        # Import place data for each country
        total_created = 0
        total_updated = 0

        for country_code in countries:
            created, updated = self._import_country(country_code, limit)
            total_created += created
            total_updated += updated

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPlace import complete: {total_created} created, {total_updated} updated"
            )
        )

        # Import alternate names if not skipped
        if not skip_altnames:
            self.stdout.write("\nImporting alternate names...")
            altnames_count = self._import_alternate_names(countries)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Alternate names import complete: {altnames_count} places updated"
                )
            )

        self.stdout.write(self.style.SUCCESS("\nImport finished successfully"))

    def _drop_all(self) -> None:
        """Drop all GeoName data without a country code."""
        count = GeoName.objects.filter(country_code="").count()
        if count == 0:
            self.stdout.write("No data without country code to drop")
            return

        confirm = input(
            f"Are you sure you want to delete {count} place records without country code? Type 'yes' to confirm: "
        )
        if confirm.lower() != "yes":
            self.stdout.write(self.style.WARNING("Drop cancelled"))
            raise SystemExit(0)

        GeoName.objects.filter(country_code="").delete()
        self.stdout.write(
            self.style.SUCCESS(f"Dropped {count} records without country code")
        )

    def _drop_countries(self, countries: list[str]) -> None:
        """Drop GeoName data for specified countries."""
        for country_code in countries:
            count = GeoName.objects.filter(country_code=country_code).count()
            if count > 0:
                GeoName.objects.filter(country_code=country_code).delete()
                self.stdout.write(
                    self.style.SUCCESS(f"Dropped {count} records for {country_code}")
                )

    def _import_country(self, country_code: str, limit: int | None) -> tuple[int, int]:
        """Import place data for a single country."""
        zip_filename = f"{country_code}.zip"
        url = f"{self.BASE_URL}{zip_filename}"

        self.stdout.write(f"\nFetching {country_code} data from: {url}")

        try:
            # Download zip file
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".zip"
            ) as tmp_zip:
                with urllib.request.urlopen(url) as response:
                    # Download in chunks
                    chunk_size = 8192
                    while chunk := response.read(chunk_size):
                        tmp_zip.write(chunk)
                tmp_zip_path = tmp_zip.name

            self.stdout.write(f"Downloaded to: {tmp_zip_path}")

            # Extract zip file
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(tmp_zip_path, "r") as zip_ref:
                    zip_ref.extractall(tmp_dir)

                # Find the .txt file (should be {CC}.txt)
                txt_file = os.path.join(tmp_dir, f"{country_code}.txt")

                if not os.path.exists(txt_file):
                    self.stdout.write(
                        self.style.ERROR(
                            f"Could not find {country_code}.txt in zip file"
                        )
                    )
                    os.unlink(tmp_zip_path)
                    return 0, 0

                self.stdout.write("Processing records...")
                created, updated = self._process_country_file(txt_file, limit)

            # Clean up zip file
            os.unlink(tmp_zip_path)

            self.stdout.write(
                self.style.SUCCESS(
                    f"  {country_code}: {created} created, {updated} updated"
                )
            )
            return created, updated

        except urllib.error.HTTPError as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to download {country_code} data: {e}")
            )
            return 0, 0
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error processing {country_code}: {e}"))
            import traceback

            traceback.print_exc()
            return 0, 0

    def _process_country_file(
        self, filepath: str, limit: int | None
    ) -> tuple[int, int]:
        """Process a country data file."""
        created_count = 0
        updated_count = 0
        processed_count = 0

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")

            batch = []
            batch_size = 1000

            for row in reader:
                if limit and processed_count >= limit:
                    break

                try:
                    place_data = self._parse_row(row)
                    if place_data:
                        batch.append(place_data)
                        processed_count += 1  # Increment here when we add to batch

                    if len(batch) >= batch_size:
                        c, u = self._save_batch(batch)
                        created_count += c
                        updated_count += u
                        batch = []

                        if processed_count % 10000 == 0:
                            self.stdout.write(
                                f"  Processed {processed_count} records..."
                            )

                        # Check limit after saving batch
                        if limit and processed_count >= limit:
                            break

                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Error parsing row: {e}"))
                    continue

            # Save remaining batch (respecting limit)
            if batch:
                c, u = self._save_batch(batch)
                created_count += c
                updated_count += u

        return created_count, updated_count

    def _parse_row(self, row: list[str]) -> dict | None:
        """Parse a row from GeoNames data file."""
        if len(row) < 19:
            return None

        try:
            # GeoNames format:
            # 0: geonameid
            # 1: name
            # 2: asciiname
            # 3: alternatenames (comma-separated)
            # 4: latitude
            # 5: longitude
            # 6: feature class
            # 7: feature code
            # 8: country code
            # 9: cc2
            # 10: admin1 code
            # 11: admin2 code
            # 12: admin3 code
            # 13: admin4 code
            # 14: population
            # 15: elevation
            # 16: dem (digital elevation model)
            # 17: timezone
            # 18: modification date

            geoname_id = int(row[0])
            name = row[1]
            ascii_name = row[2]
            latitude = float(row[4])
            longitude = float(row[5])
            feature_class = row[6]
            feature_code = row[7]
            country_code = row[8]
            admin1_code = row[10]
            admin2_code = row[11]
            admin3_code = row[12]
            admin4_code = row[13]

            population = int(row[14]) if row[14] else None
            elevation = int(row[15]) if row[15] else None
            timezone = row[17]

            # Parse modification date
            mod_date = None
            if row[18]:
                try:
                    mod_date = datetime.strptime(row[18], "%Y-%m-%d").date()
                except ValueError:
                    pass

            return {
                "geoname_id": geoname_id,
                "name": name,
                "ascii_name": ascii_name,
                "feature_id": f"{feature_class}.{feature_code}",  # Composite ID for Feature FK
                "location": Point(longitude, latitude, srid=4326),
                "elevation": elevation,
                "population": population,
                "country_code": country_code,
                "admin1_code": admin1_code,
                "admin2_code": admin2_code,
                "admin3_code": admin3_code,
                "admin4_code": admin4_code,
                "timezone": timezone,
                "modification_date": mod_date,
                "is_deleted": False,
            }

        except (ValueError, IndexError) as e:
            self.stdout.write(self.style.WARNING(f"Error parsing row: {e}"))
            return None

    def _save_batch(self, batch: list[dict]) -> tuple[int, int]:
        """Save a batch of place data using efficient bulk operations."""
        from ...models import Feature

        created_count = 0
        updated_count = 0

        if not batch:
            return 0, 0

        with transaction.atomic():
            # Get all unique feature IDs from this batch
            feature_ids = set(place_data["feature_id"] for place_data in batch)

            # Load all features in one query - verify they exist
            existing_features = set(
                Feature.objects.filter(id__in=feature_ids).values_list("id", flat=True)
            )

            # Extract geoname IDs from batch
            geoname_ids = [place_data["geoname_id"] for place_data in batch]

            # Find existing records in one query
            existing_ids = set(
                GeoName.objects.filter(geoname_id__in=geoname_ids).values_list(
                    "geoname_id", flat=True
                )
            )

            # Separate into create and update batches
            to_create = []
            to_update = []

            for place_data in batch:
                geoname_id = place_data["geoname_id"]
                feature_id = place_data["feature_id"]

                # Verify feature exists (should exist from migration)
                if feature_id not in existing_features:
                    # Skip if feature doesn't exist
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping geoname {geoname_id}: feature {feature_id} not found"
                        )
                    )
                    continue

                if geoname_id in existing_ids:
                    to_update.append(place_data)
                else:
                    to_create.append(place_data)

            # Bulk create new records
            if to_create:
                GeoName.objects.bulk_create(
                    [GeoName(**data) for data in to_create],
                    batch_size=500,
                )
                created_count = len(to_create)

            # Bulk update existing records
            if to_update:
                update_objects = []
                for data in to_update:
                    obj = GeoName(geoname_id=data["geoname_id"])
                    for key, value in data.items():
                        setattr(obj, key, value)
                    update_objects.append(obj)

                GeoName.objects.bulk_update(
                    update_objects,
                    fields=[
                        "name",
                        "ascii_name",
                        "feature_id",
                        "location",
                        "elevation",
                        "population",
                        "country_code",
                        "admin1_code",
                        "admin2_code",
                        "admin3_code",
                        "admin4_code",
                        "timezone",
                        "modification_date",
                        "is_deleted",
                    ],
                    batch_size=500,
                )
                updated_count = len(to_update)

        return created_count, updated_count

    def _import_alternate_names(self, countries: list[str]) -> int:
        """Import alternate names from country-specific files."""
        updated_count = 0

        for country_code in countries:
            self.stdout.write(f"\nFetching alternate names for {country_code}...")

            # Try country-specific alternate names file
            url = f"{self.ALTNAMES_URL}{country_code}.zip"

            try:
                # Download zip file
                with tempfile.NamedTemporaryFile(
                    mode="wb", delete=False, suffix=".zip"
                ) as tmp_zip:
                    with urllib.request.urlopen(url) as response:
                        chunk_size = 8192
                        while chunk := response.read(chunk_size):
                            tmp_zip.write(chunk)
                    tmp_zip_path = tmp_zip.name

                # Extract and process
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with zipfile.ZipFile(tmp_zip_path, "r") as zip_ref:
                        zip_ref.extractall(tmp_dir)

                    txt_file = os.path.join(tmp_dir, f"{country_code}.txt")

                    if os.path.exists(txt_file):
                        count = self._process_alternate_names_file(txt_file)
                        updated_count += count
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  Updated {count} places with alternate names"
                            )
                        )

                os.unlink(tmp_zip_path)

            except urllib.error.HTTPError:
                self.stdout.write(
                    self.style.WARNING(
                        f"No alternate names file for {country_code} (this is normal for some countries)"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(
                        f"Error loading alternate names for {country_code}: {e}"
                    )
                )

        return updated_count

    def _process_alternate_names_file(self, filepath: str) -> int:
        """Process alternate names file and create AlternativeName records using bulk operations."""
        from django.conf import settings

        # Get allowed language codes from settings
        allowed_languages = set(settings.LANGUAGE_CODES)

        # Collect alternate name records
        altname_records = []

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")

            for row in reader:
                if len(row) < 4:
                    continue

                try:
                    # Format: alternateNameId, geonameId, isolanguage, alternate name, isPreferredName, isShortName, isColloquial, isHistoric, from, to
                    alternatename_id = int(row[0])
                    geoname_id = int(row[1])
                    iso_language = row[2] if len(row) > 2 else ""
                    alternate_name = row[3] if len(row) > 3 else ""
                    is_preferred = row[4] == "1" if len(row) > 4 else False
                    is_short = row[5] == "1" if len(row) > 5 else False
                    is_colloquial = row[6] == "1" if len(row) > 6 else False
                    is_historic = row[7] == "1" if len(row) > 7 else False
                    from_period = row[8] if len(row) > 8 else ""
                    to_period = row[9] if len(row) > 9 else ""

                    # Only include names in allowed languages
                    # Skip special codes like 'post', 'link', 'unlc', 'iata', 'icao', etc.
                    if alternate_name and iso_language in allowed_languages:
                        altname_records.append(
                            {
                                "alternatename_id": alternatename_id,
                                "geoname_id": geoname_id,
                                "iso_language": iso_language,
                                "alternate_name": alternate_name,
                                "is_preferred_name": is_preferred,
                                "is_short_name": is_short,
                                "is_colloquial": is_colloquial,
                                "is_historic": is_historic,
                                "from_period": from_period,
                                "to_period": to_period,
                            }
                        )
                except (ValueError, IndexError):
                    continue

        # Get existing geoname_ids to verify foreign key relationships
        geoname_ids = set(record["geoname_id"] for record in altname_records)
        existing_geonames = set(
            GeoName.objects.filter(geoname_id__in=geoname_ids).values_list(
                "geoname_id", flat=True
            )
        )

        # Filter out records where the geoname doesn't exist
        valid_records = [
            record
            for record in altname_records
            if record["geoname_id"] in existing_geonames
        ]

        # Get existing alternatename_ids to separate create from update
        alternatename_ids = [record["alternatename_id"] for record in valid_records]
        existing_altname_ids = set(
            AlternativeName.objects.filter(
                alternatename_id__in=alternatename_ids
            ).values_list("alternatename_id", flat=True)
        )

        # Separate into create and update batches
        to_create = []
        to_update = []

        for record in valid_records:
            if record["alternatename_id"] in existing_altname_ids:
                to_update.append(record)
            else:
                to_create.append(record)

        # Bulk create new records
        created_count = 0
        if to_create:
            batch_size = 500
            for i in range(0, len(to_create), batch_size):
                batch = to_create[i : i + batch_size]
                with transaction.atomic():
                    AlternativeName.objects.bulk_create(
                        [AlternativeName(**data) for data in batch],
                        batch_size=500,
                        ignore_conflicts=True,  # Skip duplicates
                    )
                created_count += len(batch)

                if created_count % 5000 == 0:
                    self.stdout.write(f"  Created {created_count} alternative names...")

        # Bulk update existing records
        updated_count = 0
        if to_update:
            batch_size = 500
            for i in range(0, len(to_update), batch_size):
                batch = to_update[i : i + batch_size]

                update_objects = []
                for data in batch:
                    obj = AlternativeName(alternatename_id=data["alternatename_id"])
                    for key, value in data.items():
                        setattr(obj, key, value)
                    update_objects.append(obj)

                with transaction.atomic():
                    AlternativeName.objects.bulk_update(
                        update_objects,
                        fields=[
                            "geoname_id",
                            "iso_language",
                            "alternate_name",
                            "is_preferred_name",
                            "is_short_name",
                            "is_colloquial",
                            "is_historic",
                            "from_period",
                            "to_period",
                        ],
                        batch_size=500,
                    )
                updated_count += len(batch)

                if updated_count % 5000 == 0:
                    self.stdout.write(f"  Updated {updated_count} alternative names...")

        total = created_count + updated_count
        self.stdout.write(f"  Total: {created_count} created, {updated_count} updated")
        return total
