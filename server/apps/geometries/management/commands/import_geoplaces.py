"""
Management command to import GeoPlace data from external_geonames.

Imports enabled GeoNames features into curated GeoPlace model.
Calculates importance scores and handles deduplication.

Usage:
    app import_geoplaces --source geonames                     # Import from enabled GeoNames features
    app import_geoplaces --source geonames --dry-run           # Dry run to see what would be imported
    app import_geoplaces --source geonames -c ch,fr            # Limit to specific countries
    app import_geoplaces --source geonames -c alps             # Import all Alpine countries
    app import_geoplaces --source geonames --update            # Update existing places
    app import_geoplaces --source geonames -l 1000             # Import max 1000 entries (testing)
    app import_geoplaces --source wodore                       # Import huts into GeoPlace for search
"""

import math
from typing import Tuple

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core.management.base import BaseCommand, CommandParser

from server.apps.external_geonames.management.commands._country_groups import (
    expand_countries,
)
from server.apps.external_geonames.models import Feature, GeoName
from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut


class Command(BaseCommand):
    help = "Import GeoPlace data from external GeoNames"
    batch_size = 100
    default_hut_importance = 80

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source",
            type=str,
            default="geonames",
            choices=["geonames", "wodore"],
            help="Source to import from",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "-c",
            "--countries",
            type=str,
            help="Comma-separated country codes or group name (e.g., 'ch,de' or 'alps' for AT,CH,DE,FR,IT,LI,MC,SI)",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing places instead of skipping them",
        )
        parser.add_argument(
            "-l",
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
            expand_countries(options["countries"]) if options["countries"] else None
        )
        update = options["update"]
        limit = options["limit"]
        min_importance = options["min_importance"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        source_handlers = {
            "geonames": self._import_from_geonames,
            "wodore": self._import_from_wodore,
        }

        handler = source_handlers.get(source)
        if not handler:
            self.stdout.write(self.style.ERROR(f"Unknown source: {source}"))
            return

        created, updated, skipped = handler(
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

    def _normalize_elevation(self, elevation: float | int | None) -> int | None:
        if elevation is None:
            return None
        try:
            if float(elevation) == 0:
                return None
            return int(round(float(elevation)))
        except (TypeError, ValueError):
            return None

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
        enabled_features = list(
            Feature.objects.filter(
                is_enabled=True,
                category__isnull=False,
            ).select_related("category", "category__parent")
        )

        if not enabled_features:
            self.stdout.write(
                self.style.WARNING(
                    "No enabled features with categories found. "
                    "Please enable features and assign categories in admin."
                )
            )
            return 0, 0, 0

        self.stdout.write(
            f"Found {len(enabled_features)} enabled features with categories assigned:"
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
        processed = 0
        for geoname in queryset.iterator(chunk_size=self.batch_size):
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
                if processed % self.batch_size == 0:
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
                if existing_place:
                    if update:
                        # Update existing place (only if changed)
                        was_updated = self._update_place(
                            existing_place, geoname, importance
                        )
                        if was_updated:
                            updated_count += 1
                        else:
                            skipped_count += 1
                    else:
                        # Skip existing place
                        skipped_count += 1
                else:
                    # Create new place
                    try:
                        self._create_place(geoname, importance)
                        created_count += 1
                    except Exception as e:
                        # If creation fails (e.g., race condition), try to find and update
                        existing_place = self._find_duplicate(geoname)
                        if existing_place and update:
                            was_updated = self._update_place(
                                existing_place, geoname, importance
                            )
                            if was_updated:
                                updated_count += 1
                            else:
                                skipped_count += 1
                        else:
                            raise e

            if processed % self.batch_size == 0:
                self.stdout.write(
                    f"  Processed {processed}/{total_count} ({created_count} created, {updated_count} updated, {skipped_count} skipped)"
                )

        return created_count, updated_count, skipped_count

    def _import_from_wodore(
        self,
        countries: list[str] | None,
        update: bool,
        limit: int | None,
        min_importance: int,
        dry_run: bool,
    ) -> Tuple[int, int, int]:
        """Import from huts into GeoPlace for search."""
        queryset = Hut.objects.filter(is_active=True).select_related("hut_type_open")

        if countries:
            queryset = queryset.filter(country_field__in=[c.upper() for c in countries])
            self.stdout.write(f"\nFiltering to countries: {', '.join(countries)}")

        if limit:
            queryset = queryset[:limit]
            self.stdout.write(f"Limiting to {limit} records")

        total_count = queryset.count()
        self.stdout.write(f"\nProcessing {total_count} huts...")

        created_count = 0
        updated_count = 0
        skipped_count = 0
        processed = 0

        for hut in queryset.iterator(chunk_size=self.batch_size):
            processed += 1
            importance = self._calculate_hut_importance(hut)

            if importance < min_importance:
                skipped_count += 1
                continue

            existing_place = self._find_place_by_source("wodore", hut.slug)

            if existing_place and not update:
                skipped_count += 1
                if processed % self.batch_size == 0:
                    self.stdout.write(
                        f"  Processed {processed}/{total_count} (skipped existing: {existing_place.name_i18n})"
                    )
                continue

            if dry_run:
                if existing_place:
                    self.stdout.write(
                        f"  [DRY RUN] Would update: {hut.name} ({hut.slug})"
                    )
                    updated_count += 1
                else:
                    self.stdout.write(
                        f"  [DRY RUN] Would create: {hut.name} ({hut.slug}, importance={importance})"
                    )
                    created_count += 1
            else:
                if existing_place:
                    if update:
                        was_updated = self._update_place_from_hut(
                            existing_place, hut, importance
                        )
                        if was_updated:
                            updated_count += 1
                        else:
                            skipped_count += 1
                    else:
                        skipped_count += 1
                else:
                    self._create_place_from_hut(hut, importance)
                    created_count += 1

            if processed % self.batch_size == 0:
                self.stdout.write(
                    f"  Processed {processed}/{total_count} ({created_count} created, {updated_count} updated, {skipped_count} skipped)"
                )

        return created_count, updated_count, skipped_count

    def _calculate_hut_importance(self, hut: Hut) -> int:
        return self.default_hut_importance

    def _find_place_by_source(self, source: str, source_id: str) -> GeoPlace | None:
        return (
            GeoPlace.objects.filter(
                source_associations__organization__slug=source,
                source_associations__source_id=source_id,
            )
            .order_by("id")
            .first()
        )

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
        return (
            GeoPlace.objects.filter(
                location__distance_lte=(geoname.location, D(m=30)),
                place_type=geoname.feature.category,
            )
            .annotate(distance=Distance("location", geoname.location))
            .order_by("distance")
            .first()
        )

    def _create_place(self, geoname: GeoName, importance: int) -> GeoPlace:
        """Create a new GeoPlace from GeoName data with source association."""
        place = GeoPlace.create_with_source(
            source="geonames",
            source_id=str(geoname.id),
            name=geoname.name,
            place_type=geoname.feature.category,
            location=geoname.location,
            elevation=self._normalize_elevation(geoname.elevation),
            country_code=geoname.country_code,
            importance=importance,
            is_active=True,
            is_public=True,  # Can be changed manually later
            is_modified=False,
        )
        return place

    def _update_place(self, place: GeoPlace, geoname: GeoName, importance: int) -> bool:
        """
        Update an existing GeoPlace with GeoName data.

        Returns True if the place was updated, False if no changes needed.
        """
        # Only update if not manually modified
        if place.is_modified:
            return False

        # Ensure source association exists
        place.add_source(source="geonames", source_id=str(geoname.id))

        # Check if any fields actually changed
        changed = False
        if place.name != geoname.name:
            place.name = geoname.name
            changed = True
        if place.location != geoname.location:
            place.location = geoname.location
            changed = True
        new_elevation = self._normalize_elevation(geoname.elevation)
        if place.elevation != new_elevation:
            place.elevation = new_elevation
            changed = True
        if place.importance != importance:
            place.importance = importance
            changed = True

        if changed:
            place.save(
                update_fields=[
                    "name",
                    "location",
                    "elevation",
                    "importance",
                    "modified",
                ]
            )
            return True
        return False

    def _create_place_from_hut(self, hut: Hut, importance: int) -> GeoPlace:
        return GeoPlace.create_with_source(
            source="wodore",
            source_id=hut.slug,
            name=hut.name,
            place_type=hut.hut_type_open,
            location=hut.location,
            elevation=self._normalize_elevation(hut.elevation),
            country_code=hut.country_field,
            importance=importance,
            is_active=hut.is_active,
            is_public=hut.is_public,
            is_modified=hut.is_modified,
        )

    def _update_place_from_hut(
        self, place: GeoPlace, hut: Hut, importance: int
    ) -> bool:
        if place.is_modified:
            return False

        place.add_source(source="wodore", source_id=hut.slug)

        changed = False
        if place.name != hut.name:
            place.name = hut.name
            changed = True
        if place.place_type != hut.hut_type_open:
            place.place_type = hut.hut_type_open
            changed = True
        if place.location != hut.location:
            place.location = hut.location
            changed = True
        new_elevation = self._normalize_elevation(hut.elevation)
        if place.elevation != new_elevation:
            place.elevation = new_elevation
            changed = True
        if place.country_code != hut.country_field:
            place.country_code = hut.country_field
            changed = True
        if place.importance != importance:
            place.importance = importance
            changed = True
        if place.is_active != hut.is_active:
            place.is_active = hut.is_active
            changed = True
        if place.is_public != hut.is_public:
            place.is_public = hut.is_public
            changed = True
        if place.is_modified != hut.is_modified:
            place.is_modified = hut.is_modified
            changed = True

        if changed:
            place.save(
                update_fields=[
                    "name",
                    "place_type",
                    "location",
                    "elevation",
                    "country_code",
                    "importance",
                    "is_active",
                    "is_public",
                    "is_modified",
                    "modified",
                ]
            )
            return True
        return False
