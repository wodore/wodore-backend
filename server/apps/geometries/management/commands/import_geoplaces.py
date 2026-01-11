"""
Management command to import GeoPlace data from external_geonames.

Imports enabled GeoNames features into curated GeoPlace model.
Calculates importance scores and handles deduplication.

Usage:
    app import_geoplaces --source geonames                     # Import from enabled GeoNames features
    app import_geoplaces --source geonames --dry-run           # Dry run to see what would be imported
    app import_geoplaces --source geonames --countries ch,fr   # Limit to specific countries
    app import_geoplaces --source geonames --update            # Update existing places
    app import_geoplaces --source geonames --limit 1000        # Import max 1000 entries (testing)
"""

import math
from typing import Tuple

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core.management.base import BaseCommand, CommandParser

from server.apps.external_geonames.models import Feature, GeoName
from server.apps.geometries.models import GeoPlace


class Command(BaseCommand):
    help = "Import GeoPlace data from external GeoNames"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source",
            type=str,
            default="geonames",
            choices=["geonames"],
            help="Source to import from (currently only 'geonames' supported)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "--countries",
            type=str,
            help="Comma-separated country codes to import (e.g., 'ch,fr,it')",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing places instead of skipping them",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of places to import (for testing)",
        )
        parser.add_argument(
            "--min-importance",
            type=int,
            default=0,
            help="Only import features with importance >= this value (0-100)",
        )

    def handle(self, *args, **options) -> None:
        source = options["source"]
        dry_run = options["dry_run"]
        countries = (
            [c.strip().upper() for c in options["countries"].split(",")]
            if options["countries"]
            else None
        )
        update = options["update"]
        limit = options["limit"]
        min_importance = options["min_importance"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        if source == "geonames":
            created, updated, skipped = self._import_from_geonames(
                countries=countries,
                update=update,
                limit=limit,
                min_importance=min_importance,
                dry_run=dry_run,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nImport complete: {created} created, {updated} updated, {skipped} skipped"
                )
            )
        else:
            self.stdout.write(self.style.ERROR(f"Unknown source: {source}"))

    def _import_from_geonames(
        self,
        countries: list[str] | None,
        update: bool,
        limit: int | None,
        min_importance: int,
        dry_run: bool,
    ) -> Tuple[int, int, int]:
        """Import from external_geonames GeoName model."""

        # Get enabled features with categories assigned
        enabled_features = Feature.objects.filter(
            is_enabled=True,
            category__isnull=False,
        ).select_related("category", "category__parent")

        if not enabled_features.exists():
            self.stdout.write(
                self.style.WARNING(
                    "No enabled features with categories found. "
                    "Please enable features and assign categories in admin."
                )
            )
            return 0, 0, 0

        self.stdout.write(
            f"Found {enabled_features.count()} enabled features with categories assigned:"
        )
        for feature in enabled_features:
            self.stdout.write(
                f"  - {feature.id}: {feature.name} → {feature.category.get_identifier()} (importance: {feature.importance})"
            )

        # Build query for GeoNames to import
        feature_ids = [f.id for f in enabled_features]
        queryset = GeoName.objects.filter(
            feature_id__in=feature_ids,
            is_deleted=False,
        ).select_related("feature", "feature__category")

        # Filter by countries if specified
        if countries:
            queryset = queryset.filter(country_code__in=countries)
            self.stdout.write(f"\nFiltering to countries: {', '.join(countries)}")

        # Apply limit for testing
        if limit:
            queryset = queryset[:limit]
            self.stdout.write(f"Limiting to {limit} records")

        total_count = queryset.count()
        self.stdout.write(f"\nProcessing {total_count} GeoName records...")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Process in batches
        batch_size = 100
        processed = 0

        for i in range(0, total_count, batch_size):
            batch = list(queryset[i : i + batch_size])

            for geoname in batch:
                processed += 1

                # Calculate importance for this place
                importance = self._calculate_importance(geoname)

                # Skip if below minimum importance
                if importance < min_importance:
                    skipped_count += 1
                    continue

                # Check for duplicate (proximity + name similarity)
                existing_place = self._find_duplicate(geoname)

                if existing_place and not update:
                    skipped_count += 1
                    if processed % 100 == 0:
                        self.stdout.write(
                            f"  Processed {processed}/{total_count} (skipped existing: {existing_place.name_i18n})"
                        )
                    continue

                # Create or update place
                if dry_run:
                    if existing_place:
                        self.stdout.write(
                            f"  [DRY RUN] Would update: {geoname.name} ({geoname.feature_id})"
                        )
                        updated_count += 1
                    else:
                        self.stdout.write(
                            f"  [DRY RUN] Would create: {geoname.name} ({geoname.feature_id}, importance={importance})"
                        )
                        created_count += 1
                else:
                    if existing_place and update:
                        # Update existing place
                        self._update_place(existing_place, geoname, importance)
                        updated_count += 1
                    elif not existing_place:
                        # Create new place
                        self._create_place(geoname, importance)
                        created_count += 1

                if processed % 100 == 0:
                    self.stdout.write(
                        f"  Processed {processed}/{total_count} ({created_count} created, {updated_count} updated, {skipped_count} skipped)"
                    )

        return created_count, updated_count, skipped_count

    def _calculate_importance(self, geoname: GeoName) -> int:
        """
        Calculate importance score for a place based on feature type and attributes.

        Returns a score from 0-100 where:
        - Base score comes from feature importance
        - Population adds bonus (log scale)
        - Special feature codes get bonuses
        """
        # Start with feature's base importance
        importance = geoname.feature.importance

        # Population bonus (log scale, max +20)
        if geoname.population and geoname.population > 0:
            pop_bonus = min(math.log10(geoname.population) * 2, 20)
            importance += pop_bonus

        # Feature code bonuses (from proposal)
        feature_bonuses = {
            "P.PPLC": 20,  # Capital city
            "P.PPLA": 10,  # First-order admin seat
            "P.PPLA2": 5,  # Second-order admin
            "S.RSTN": 5,  # Train station
            "H.GLCR": 5,  # Glacier
            "H.FLLS": 5,  # Waterfall
        }
        importance += feature_bonuses.get(geoname.feature_id, 0)

        # Cap at 100
        return min(int(importance), 100)

    def _find_duplicate(self, geoname: GeoName) -> GeoPlace | None:
        """
        Find existing GeoPlace that matches this GeoName.

        Uses location proximity (within 30m) and same category.
        Returns first match or None.
        """
        # Search for places within 30m with same category
        candidates = (
            GeoPlace.objects.filter(
                location__distance_lte=(geoname.location, D(m=30)),
                place_type=geoname.feature.category,
            )
            .annotate(distance=Distance("location", geoname.location))
            .order_by("distance")[:5]
        )

        # For now, just return first match if any
        # Could add name similarity check here in the future
        return candidates.first() if candidates.exists() else None

    def _create_place(self, geoname: GeoName, importance: int) -> GeoPlace:
        """Create a new GeoPlace from GeoName data."""
        place = GeoPlace.objects.create(
            name=geoname.name,
            place_type=geoname.feature.category,
            location=geoname.location,
            elevation=geoname.elevation,
            country_code=geoname.country_code,
            importance=importance,
            is_active=True,
            is_public=True,  # Can be changed manually later
            is_modified=False,
        )
        return place

    def _update_place(self, place: GeoPlace, geoname: GeoName, importance: int) -> None:
        """Update an existing GeoPlace with GeoName data."""
        # Only update if not manually modified
        if not place.is_modified:
            place.name = geoname.name
            place.location = geoname.location
            place.elevation = geoname.elevation
            place.importance = importance
            place.save(
                update_fields=[
                    "name",
                    "location",
                    "elevation",
                    "importance",
                    "modified",
                ]
            )
