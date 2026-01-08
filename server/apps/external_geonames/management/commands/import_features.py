"""
Management command to import GeoNames feature codes.

Downloads and imports feature codes from GeoNames featureCodes_en.txt.
Only adds new features - does not delete or overwrite existing ones.

Usage:
    app import_features              # Import/update feature codes
    app import_features --url <URL>  # Use custom URL
"""

import urllib.request
from io import StringIO

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from ...models import Feature


class Command(BaseCommand):
    help = "Import GeoNames feature codes (add new only, never delete)"

    DEFAULT_URL = "https://download.geonames.org/export/dump/featureCodes_en.txt"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--url",
            type=str,
            default=self.DEFAULT_URL,
            help=f"URL to fetch feature codes (default: {self.DEFAULT_URL})",
        )

    def handle(self, *args, **options) -> None:
        url = options["url"]

        self.stdout.write(f"Fetching feature codes from: {url}")

        try:
            with urllib.request.urlopen(url) as response:
                content = response.read().decode("utf-8")
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to download feature codes: {e}")
            )
            return

        self.stdout.write("Parsing feature codes...")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with transaction.atomic():
            for line in StringIO(content):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                # Format: "class.code<tab>name<tab>description"
                # Note: GeoNames only has 2 columns: code and name
                # There is no separate description field in featureCodes_en.txt
                code_full = parts[0]
                name = parts[1] if len(parts) > 1 else ""
                # Description is usually same as name in GeoNames, or can be blank
                description = parts[2] if len(parts) > 2 else ""

                # Split class.code
                if "." not in code_full:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping invalid feature code format: {code_full}"
                        )
                    )
                    continue

                feature_class, feature_code = code_full.split(".", 1)
                feature_id = code_full  # Use full "class.code" as ID

                # Only add new features, never overwrite
                feature, created = Feature.objects.get_or_create(
                    id=feature_id,
                    defaults={
                        "feature_class": feature_class,
                        "feature_code": feature_code,
                        "name": name,
                        "description": description,
                        "is_enabled": False,  # Disabled by default
                        "importance": 25,  # Default low value (0-100 scale)
                    },
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Created: {feature_class}.{feature_code} - {name}"
                        )
                    )
                else:
                    # Feature exists - only update name/description if they changed
                    # but never modify is_enabled or other config fields
                    updated = False
                    if feature.name != name:
                        feature.name = name
                        updated = True
                    if feature.description != description:
                        feature.description = description
                        updated = True
                    if feature.feature_class != feature_class:
                        feature.feature_class = feature_class
                        updated = True

                    if updated:
                        feature.save(
                            update_fields=["name", "description", "feature_class"]
                        )
                        updated_count += 1
                        self.stdout.write(
                            f"  Updated: {feature_class}.{feature_code} - {name}"
                        )
                    else:
                        skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nImport complete: {created_count} created, {updated_count} updated, {skipped_count} unchanged"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "\nNote: Features are disabled by default. "
                "Enable them in admin to include in GeoPlace import."
            )
        )
