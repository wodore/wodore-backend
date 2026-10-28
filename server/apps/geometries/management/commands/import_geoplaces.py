"""
Management command to import GeoPlace data from external_geonames.

Imports enabled GeoNames features into curated GeoPlace model.
Calculates importance scores and handles deduplication.

Performance Tips:
    - Use --continue flag for subsequent imports (skips already imported, 100x faster)
    - Use --min-importance to skip less important features
    - Limit countries with -c flag to reduce dataset size
    - First import is slow due to spatial duplicate checks
    - VPS performance: Ensure PostGIS indexes exist, use --continue

Usage:
    app import_geoplaces                                    # Import from all sources (geonames, wodore)
    app import_geoplaces -s geonames                        # Import only from GeoNames
    app import_geoplaces -s wodore                          # Import only from Wodore huts
    app import_geoplaces -s geonames,wodore                 # Import from multiple sources
    app import_geoplaces --dry-run                          # Dry run to see what would be imported
    app import_geoplaces -c ch,fr                           # Limit to specific countries
    app import_geoplaces -c alps                            # Import all Alpine countries
    app import_geoplaces --update                           # Update existing places
    app import_geoplaces -l 1000                            # Import max 1000 entries (testing)
    app import_geoplaces --continue                         # Skip already imported (MUCH faster)
"""

import math
from pathlib import Path
from typing import Any, ClassVar, override

import yaml
from django_admin_runner import register_command
from hut_services import LocationSchema

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core.management.base import BaseCommand, CommandParser

from server.apps.external_geonames.management.commands._country_groups import (
    expand_countries,
)
from server.apps.external_geonames.models import Feature, GeoName
from server.apps.geometries.models import GeoPlace
from server.apps.geometries.schemas import (
    GeoPlaceBaseInput,
    PlaceTypeInput,
    SourceInput,
)
from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization
from server.core import UpdateCreateStatus


@register_command(group="Geometries", timeout=21600)
class Command(BaseCommand):
    help = "Import GeoPlace data from external GeoNames"
    batch_size = 500  # Increased from 100 for better VPS performance
    default_hut_importance = 80

    #: Exhaustive ``hut_type_closed`` → season-classifier mapping
    #: (OpenSpec geoplace-capacity-and-types-via-categories, design D2
    #: + advisor review finding 2 — every HutTypeEnum value has an
    #: explicit entry; ``None`` means no classifier = unknown season).
    #: Live-data distribution (active huts): selfhut 212, closed 55,
    #: bivouac 4, unknown 41 — the rest never occur as closed types.
    _CLOSED_TYPE_TO_SEASON: ClassVar[dict[str, str | None]] = {
        "unknown": None,  # unknown season (advisor: explicit, not silent)
        "closed": "season.closed",
        # basic shelter doubles as winter accommodation (hut-services
        # CapacitySchema hint: "shelter, winterroom")
        "shelter": "season.winter_room",
        "bivouac": "season.winter_room",
        "selfhut": "season.self_service",
        "camping": "season.summer_only",
        "campgr": None,  # unattended campground — no clear season semantics yet
        # staffed / summer-season family (design D2 "hotel-family")
        "bhotel": "season.summer_only",
        "hostel": "season.summer_only",
        "hotel": "season.summer_only",
        "resta": "season.summer_only",
        "hut": None,  # a closed hut is still a hut — no season claim
        "alp": None,  # alp: seasonal by nature, source states nothing
        "special": None,  # design open question resolved: unknown
    }

    #: Open types that keep operating unstaffed year-round when the
    #: source sets no closed type (proposal: "unstaffed year-round →
    #: season.year_round"). Hut.update_or_create derives selfhut/
    #: bivouac closed types from ``capacity_closed`` (_hut.py) — the
    #: import reads the *resolved* FK, so the derivation rule is
    #: honored automatically.
    _YEAR_ROUND_OPEN_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"shelter", "selfhut", "bivouac"}
    )

    @staticmethod
    def _truncate_name(name: str, max_length: int = 200) -> str:
        """
        Truncate name to max_length if necessary.

        Args:
            name: The name to truncate
            max_length: Maximum allowed length (default 200)

        Returns:
            Truncated name with ellipsis if truncated
        """
        if len(name) <= max_length:
            return name
        # Truncate and add ellipsis
        return name[: max_length - 3] + "..."

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-s",
            "--sources",
            type=str,
            default="geonames,wodore",
            help="Comma-separated list of sources to import from (default: all sources)",
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
        parser.add_argument(
            "--continue",
            dest="continue_import",
            action="store_true",
            help="Continue from last imported entry (skips already imported GeoNames efficiently)",
        )
        parser.add_argument(
            "--drop",
            action="store_true",
            help="Drop all GeoPlaces from specified sources before importing (use with caution!)",
        )

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        sources_str = options["sources"]
        dry_run = options["dry_run"]
        countries = (
            expand_countries(options["countries"]) if options["countries"] else None
        )
        update = options["update"]
        limit = options["limit"]
        min_importance = options["min_importance"]
        continue_import = options["continue_import"]
        drop = options["drop"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Safety check for --drop flag
        if drop and not dry_run:
            self.stdout.write(
                self.style.ERROR(
                    "\n"
                    "⚠️  WARNING: --drop flag will DELETE all GeoPlaces from the specified sources!\n"
                    "   This action cannot be undone!\n"
                )
            )
            confirmation = input('Type "DELETE" to confirm: ')
            if confirmation != "DELETE":
                self.stdout.write(self.style.ERROR("Aborted by user."))
                return

        # Parse sources
        sources = [s.strip() for s in sources_str.split(",") if s.strip()]
        valid_sources = ["geonames", "wodore"]

        # Validate sources
        invalid_sources = [s for s in sources if s not in valid_sources]
        if invalid_sources:
            self.stdout.write(
                self.style.ERROR(
                    f"Invalid source(s): {', '.join(invalid_sources)}. "
                    f"Valid options: {', '.join(valid_sources)}"
                )
            )
            return

        self.stdout.write(f"Importing from sources: {', '.join(sources)}")

        # Ensure required organizations exist for all sources
        for source in sources:
            self._ensure_organizations_exist(source, dry_run)

        # Drop existing GeoPlaces if --drop flag is set
        if drop:
            self.stdout.write(self.style.WARNING("\n" + "=" * 60))
            self.stdout.write(
                self.style.WARNING(
                    "Dropping existing GeoPlaces from specified sources..."
                )
            )
            self.stdout.write(self.style.WARNING("=" * 60 + "\n"))
            for source in sources:
                deleted_count = self._drop_places_by_source(source, dry_run)
                if not dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Deleted {deleted_count} places from '{source}'"
                        )
                    )

        source_handlers = {
            "geonames": self._import_from_geonames,
            "wodore": self._import_from_wodore,
        }

        # Process each source
        total_created = 0
        total_updated = 0
        total_skipped = 0

        for source in sources:
            handler = source_handlers.get(source)
            if not handler:
                self.stdout.write(self.style.ERROR(f"Unknown source: {source}"))
                continue

            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(f"Processing source: {source}")
            self.stdout.write("=" * 60)

            created, updated, skipped = handler(
                countries=countries,
                update=update,
                limit=limit,
                min_importance=min_importance,
                dry_run=dry_run,
                continue_import=continue_import,
            )

            total_created += created
            total_updated += updated
            total_skipped += skipped

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'=' * 60}\n"
                f"Total import complete:\n"
                f"  {total_created} created\n"
                f"  {total_updated} updated\n"
                f"  {total_skipped} skipped\n"
                f"{'=' * 60}"
            )
        )

    def _normalize_elevation(self, elevation: float | None) -> int | None:
        if elevation is None:
            return None
        try:
            if float(elevation) == 0:
                return None
            return int(round(float(elevation)))
        except (TypeError, ValueError):
            return None

    def _ensure_organizations_exist(self, source: str, dry_run: bool) -> None:
        """
        Ensure required organizations exist. Create them if missing.

        Strategy:
        1. Try to load from fixture file (organizations.yaml) for full details
        2. Fall back to minimal creation if fixture not found

        This allows the import to work even if the fixtures haven't been loaded yet.
        Users can later run 'app organizations --add' to load/update fixture data.
        """
        # Fallback minimal data if fixture not available
        fallback_orgs = {
            "geonames": {
                "name": "GeoNames",
                "fullname": "GeoNames",
                "url": "https://www.geonames.org",
                "attribution": "(C) GeoNames",
            },
            "wodore": {
                "name": "Wodore",
                "fullname": "Wodore",
                "url": "https://wodore.com",
            },
        }

        slug = source
        try:
            Organization.objects.get(slug=slug)
            self.stdout.write(f"Organization '{slug}' already exists")
            return
        except Organization.DoesNotExist:
            pass  # Need to create it

        # Try to load from fixture first
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "organizations"
            / "fixtures"
            / "organizations.yaml"
        )

        org_data: dict[str, Any] | None = None
        if fixture_path.exists():
            try:
                with open(fixture_path) as f:
                    fixtures = yaml.safe_load(f)
                for item in fixtures:
                    if item.get("model") == "organizations.organization":
                        if item.get("fields", {}).get("slug") == slug:
                            # Remove pk to avoid conflicts, let Django auto-generate
                            fields = item["fields"].copy()
                            fields.pop("id", None)
                            org_data = fields
                            self.stdout.write(f"Found '{slug}' in fixture file")
                            break
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Could not load fixture file: {e}")
                )

        # Fall back to minimal data if not in fixture
        if not org_data:
            org_data = fallback_orgs.get(slug, {})
            org_data["slug"] = slug
            org_data["is_active"] = True  # type: ignore  # defaults dict accepts bool at runtime
            org_data["is_public"] = False  # type: ignore  # defaults dict accepts bool at runtime
            self.stdout.write(f"Using minimal data for '{slug}' (not in fixture)")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"[DRY RUN] Would create organization: {slug}")
            )
        else:
            Organization.objects.create(**org_data)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created organization '{slug}' "
                    f"(run 'app organizations --add' to load/update full fixture details)"
                )
            )

    def _import_from_geonames(
        self,
        countries: list[str] | None,
        update: bool,
        limit: int | None,
        min_importance: int,
        dry_run: bool,
        continue_import: bool = False,
    ) -> tuple[int, int, int]:
        """Import from external_geonames GeoName model.

        Args:
            countries: Filter by country codes
            update: Update existing places
            limit: Limit number of imports
            min_importance: Minimum importance score
            dry_run: Show what would be done without making changes
            continue_import: Skip already imported GeoNames efficiently
        """

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

        # Efficient skip: get all already imported GeoName IDs in one query
        imported_geoname_ids = set()
        if continue_import:
            self.stdout.write(
                self.style.NOTICE(
                    "Continue mode: Fetching already imported GeoNames..."
                )
            )
            imported_geoname_ids = set(
                GeoPlace.objects.filter(
                    source_associations__organization__slug="geonames",
                    source_associations__source_id__isnull=False,
                ).values_list("source_associations__source_id", flat=True)
            )
            self.stdout.write(
                f"Found {len(imported_geoname_ids)} already imported GeoNames"
            )
            # Exclude already imported from queryset
            if imported_geoname_ids:
                queryset = queryset.exclude(geoname_id__in=imported_geoname_ids)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Excluding {len(imported_geoname_ids)} already imported from queryset"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No imported GeoNames found - this will import everything!"
                    )
                )

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
            # Skip this check in continue_import mode since we already excluded imported IDs
            existing_place = None if continue_import else self._find_duplicate(geoname)

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
                        # If creation fails (e.g., race condition), try to find
                        # and update — but only when a duplicate exists and
                        # updates are enabled; otherwise re-raise.
                        existing_place = self._find_duplicate(geoname)
                        if not existing_place:
                            raise e
                        if not update:
                            raise e
                        was_updated = self._update_place(
                            existing_place, geoname, importance
                        )
                        if was_updated:
                            updated_count += 1
                        else:
                            skipped_count += 1

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
        continue_import: bool = False,
    ) -> tuple[int, int, int]:
        """Import from huts into GeoPlace (schema path).

        OpenSpec ``geoplace-capacity-and-types-via-categories`` task
        2.2: every active Hut rides ``GeoPlace.update_or_create`` —
        category from ``hut_type_open``, season classifier from
        ``hut_type_closed`` (mapping above), capacities in association
        ``extra``. The owner party keeps riding ``_ensure_hut_party``
        (``merge_owner`` dedups by owner slug — the schema party path
        would dedup by name and duplicate existing merged parties).
        Re-imports respect the protected-fields policy (AUTO_PROTECT).

        Args:
            countries: Filter by country codes
            update: Update existing places
            limit: Limit number of imports
            min_importance: Minimum importance score
            dry_run: Show what would be done without making changes
            continue_import: Not used for wodore source (kept for signature compatibility)
        """
        queryset = Hut.objects.filter(is_active=True).select_related(
            "hut_type_open", "hut_type_closed", "hut_owner"
        )

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

            # ``--continue`` skips already-imported places even with
            # ``--update`` (same semantics as the geonames handler).
            if existing_place and (not update or continue_import):
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
                continue

            schema = self._hut_to_place_input(hut, importance)
            place, status = GeoPlace.update_or_create(
                schema=schema,
                from_source=SourceInput(slug="wodore", source_id=hut.slug),
            )
            self._ensure_hut_party(place, hut)

            if status == UpdateCreateStatus.created:
                created_count += 1
            elif status == UpdateCreateStatus.updated:
                updated_count += 1
            else:
                skipped_count += 1

            if processed % self.batch_size == 0:
                self.stdout.write(
                    f"  Processed {processed}/{total_count} ({created_count} created, {updated_count} updated, {skipped_count} skipped)"
                )

        return created_count, updated_count, skipped_count

    def _hut_to_place_input(self, hut: Hut, importance: int) -> GeoPlaceBaseInput:
        """Build the geoplace schema input for a hut (task 2.2)."""
        place_types: list[str | PlaceTypeInput] = []
        if hut.hut_type_open is not None:
            place_types.append(
                PlaceTypeInput(
                    identifier=hut.hut_type_open.identifier,
                    classifier=self._season_classifier_identifier(hut),
                    extra={
                        key: value
                        for key, value in {
                            "capacity_open": hut.capacity_open,
                            "capacity_closed": hut.capacity_closed,
                        }.items()
                        if value is not None
                    },
                )
            )
        return GeoPlaceBaseInput(
            name=hut.name,
            location=LocationSchema(lon=hut.location.x, lat=hut.location.y),
            elevation=self._normalize_elevation(hut.elevation),  # type: ignore  # argument typing drift vs stubs
            country_code=str(hut.country_field),
            importance=importance,
            is_active=hut.is_active,
            is_public=hut.is_public,
            place_type_identifiers=place_types,
        )

    def _season_classifier_identifier(self, hut: Hut) -> str | None:
        """Map a hut's types onto the season classifier identifier."""
        if hut.hut_type_closed is not None:
            return self._CLOSED_TYPE_TO_SEASON.get(hut.hut_type_closed.slug)
        if (
            hut.hut_type_open is not None
            and hut.hut_type_open.slug in self._YEAR_ROUND_OPEN_TYPES
        ):
            return "season.year_round"
        return None

    def _calculate_hut_importance(self, _hut: Hut) -> int:
        return self.default_hut_importance

    def _find_place_by_source(self, source: str, source_id: str) -> GeoPlace | None:
        """
        Find existing GeoPlace by source organization and source_id.

        Performance: Uses indexed fields (source_id, organization.slug) for fast lookup.
        """
        return (
            GeoPlace.objects.filter(
                source_associations__organization__slug=source,
                source_associations__source_id=source_id,
            )
            .order_by("id")
            .first()
        )

    def _drop_places_by_source(self, source: str, dry_run: bool) -> int:
        """
        Drop all GeoPlaces from a specific source.

        Args:
            source: Source organization slug (e.g., 'geonames', 'wodore')
            dry_run: If True, only count without deleting

        Returns:
            Number of places deleted
        """
        # Count places to be deleted
        places_to_delete = GeoPlace.objects.filter(
            source_associations__organization__slug=source
        )
        count = places_to_delete.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would delete {count} places from '{source}'"
                )
            )
            return count

        # Delete all places (cascade will handle associations)
        places_to_delete.delete()
        return count

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
        importance += feature_bonuses.get(geoname.feature.feature_code, 0)

        # Cap at 100
        return min(math.floor(importance), 100)

    def _find_duplicate(self, geoname: GeoName) -> GeoPlace | None:
        """
        Find existing GeoPlace that matches this GeoName.

        Uses location proximity (within 30m) and same category.
        Returns first match or None.

        Performance: This uses a spatial query which can be slow on VPS.
        Consider using --continue flag to skip this check for already imported entries.
        """
        # Search for places within 30m with same category
        return (
            GeoPlace.objects.filter(
                location__distance_lte=(geoname.location, D(m=30)),
                categories=geoname.feature.category,
            )
            .annotate(distance=Distance("location", geoname.location))
            .order_by("distance")
            .first()
        )

    def _create_place(self, geoname: GeoName, importance: int) -> GeoPlace:
        """Create a new GeoPlace from GeoName data with source association."""
        place = GeoPlace.create_with_source(
            source="geonames",
            source_id=str(geoname.geoname_id),
            name=self._truncate_name(geoname.name),
            location=geoname.location,
            elevation=self._normalize_elevation(geoname.elevation),
            country_code=geoname.country_code,
            importance=importance,
            is_active=True,
            is_public=True,  # Can be changed manually later
            is_modified=False,
        )
        place.categories.add(geoname.feature.category)
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
        place.add_source(source="geonames", source_id=str(geoname.geoname_id))

        # Check if any fields actually changed
        changed = False
        truncated_name = self._truncate_name(geoname.name)
        if place.name != truncated_name:
            place.name = truncated_name
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
        if (
            geoname.feature.category
            and not place.categories.filter(id=geoname.feature.category_id).exists()
        ):
            place.categories.add(geoname.feature.category)
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

    def _ensure_hut_party(self, place: GeoPlace, hut: Hut) -> None:
        """Write the hut's owning/operating party as a role.operator
        association (OpenSpec geoplace-parties task 3.2).

        Idempotent: get_or_create on both the merged party and the
        association. Owners are merged into parties on the fly so the
        import works with or without a prior ``import_parties`` run.
        """
        from server.apps.categories.models import Category
        from server.apps.geometries.models import GeoPlaceParty
        from server.apps.parties.services import merge_owner

        if not hut.hut_owner:
            return

        role = getattr(self, "_operator_role", None)
        if role is None:
            role = Category.objects.get(identifier="role.operator")
            self._operator_role = role  # type: ignore[attr-defined]  # per-run cache

        party, _created, _linked = merge_owner(hut.hut_owner)
        GeoPlaceParty.objects.get_or_create(geo_place=place, party=party, role=role)
