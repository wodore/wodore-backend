"""
Management command to import amenities from OpenStreetMap.

Imports amenities from OSM via Geofabrik PBF files using category mappings.
Handles deduplication, opening hours parsing, and category management.

Usage:
    app geoplaces_import_osm europe/switzerland                           # Import all enabled categories
    app geoplaces_import_osm europe/alps --categories groceries,restaurant # Import specific categories
    app geoplaces_import_osm --dry-run europe/switzerland                 # Dry run (no DB changes)
    app geoplaces_import_osm -l 100 europe/switzerland                    # Limit to 100 records
    app geoplaces_import_osm --data-dir /data/osm europe/switzerland      # Cache downloads
"""

import tempfile
from datetime import datetime
from pathlib import Path

import httpx
import osmium
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from server.apps.categories.models import Category
from server.apps.geometries.config.osm_categories import (
    get_categories,
    get_enabled_categories,
    match_tags_to_category,
)
from server.apps.geometries.models import AmenityDetail, GeoPlace
from server.apps.organizations.models import Organization


class OSMHandler(osmium.SimpleHandler):
    """Handler for parsing OSM PBF files using category mappings."""

    def __init__(self, category_names: list[str] = None):
        super().__init__()
        self.amenities = []
        self.category_names = category_names

        # Get categories for matching
        if category_names:
            self.categories = get_categories(category_names)
        else:
            self.categories = get_enabled_categories()

    def node(self, n):
        """Process OSM nodes (point features)."""
        # Check if this matches any category
        tags = dict(n.tags)
        match_result = match_tags_to_category(tags, self.category_names)

        if match_result:
            category_slug, mapping, category_mappings = match_result

            # Pre-process tags if hook exists
            if mapping.pre_process:
                tags = mapping.pre_process(tags)

            # Extract amenity data
            data = self._extract_amenity_data(
                osm_type="node",
                osm_id=n.id,
                lat=n.location.lat,
                lon=n.location.lon,
                tags=tags,
                category_slug=category_slug,
                mapping=mapping,
            )

            # Post-process data if hook exists
            if mapping.post_process:
                data = mapping.post_process(tags, data)

            self.amenities.append(data)

    def way(self, w):
        """Process OSM ways (polygon features)."""
        tags = dict(w.tags)
        match_result = match_tags_to_category(tags, self.category_names)

        if not match_result:
            return

        category_slug, mapping, category_mappings = match_result

        # Pre-process tags if hook exists
        if mapping.pre_process:
            tags = mapping.pre_process(tags)

        # Calculate centroid from way nodes (locations are provided by NodeLocationsForWays)
        lons, lats = [], []
        for node in w.nodes:
            if node.location.valid():
                lons.append(node.location.lon)
                lats.append(node.location.lat)

        if not lons:
            return

        # Simple centroid calculation
        centroid_lon = sum(lons) / len(lons)
        centroid_lat = sum(lats) / len(lats)

        # Extract amenity data
        data = self._extract_amenity_data(
            osm_type="way",
            osm_id=w.id,
            lat=centroid_lat,
            lon=centroid_lon,
            tags=tags,
            category_slug=category_slug,
            mapping=mapping,
        )

        # Post-process data if hook exists
        if mapping.post_process:
            data = mapping.post_process(tags, data)

        self.amenities.append(data)

    def _extract_amenity_data(
        self,
        osm_type: str,
        osm_id: int,
        lat: float,
        lon: float,
        tags: dict,
        category_slug: str,
        mapping,
    ) -> dict:
        """Extract amenity data from OSM element."""
        return {
            "osm_type": osm_type,
            "osm_id": osm_id,
            "lat": lat,
            "lon": lon,
            "tags": tags,
            "category_slug": category_slug,
            "mapcomplete_theme": mapping.mapcomplete_theme,
            "name": tags.get("name", ""),
            "opening_hours": tags.get("opening_hours"),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "brand": tags.get("brand"),
        }


class Command(BaseCommand):
    help = "Import amenities from OpenStreetMap via Geofabrik"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "region",
            type=str,
            help="Geofabrik region path (e.g., europe/switzerland, europe/alps)",
        )
        parser.add_argument(
            "--categories",
            type=str,
            default=None,
            help="Comma-separated list of categories to import (default: all enabled categories)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without making changes",
        )
        parser.add_argument(
            "-l",
            "--limit",
            type=int,
            default=None,
            help="Limit number of places to import (for testing)",
        )
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory for PBF files (default: use temp dir). Files are cached and not re-downloaded.",
        )
        parser.add_argument(
            "--drop",
            action="store_true",
            help="Drop all existing places with specified categories (standalone operation, no import)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt when using --drop",
        )

    def handle(self, *args, **options):
        """Main command execution."""
        region = options["region"]
        dry_run = options["dry_run"]
        limit = options.get("limit")
        data_dir = options.get("data_dir")
        drop = options.get("drop", False)
        force = options.get("force", False)
        run_start = timezone.now()

        # Parse categories
        category_names = None
        if options.get("categories"):
            category_names = [c.strip() for c in options["categories"].split(",")]
        else:
            enabled = get_enabled_categories()
            category_names = [cat.category for cat in enabled]

        # Show category details
        categories = get_categories(category_names)
        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 60}"))
        self.stdout.write(
            self.style.SUCCESS(f"Importing {len(category_names)} categories:")
        )
        for cat in categories:
            mapping_count = len(cat.mappings)
            self.stdout.write(
                f"  • {cat.category}: {mapping_count} mappings ({cat.detail_type})"
            )
        self.stdout.write(self.style.SUCCESS(f"{'=' * 60}\n"))

        # 1. Drop existing places if requested (standalone operation)
        if drop:
            self.stdout.write("Counting existing places...")
            count = self._count_places(category_names)

            if count == 0:
                self.stdout.write(self.style.SUCCESS("No places found to delete"))
                return

            self.stdout.write(f"Found {count} places to delete")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(f"[DRY RUN] Would delete {count} places")
                )
                return

            # Confirmation prompt unless --force is used
            if not force:
                response = input(f"Dropping {count} entries, continue [y/N]? ")
                if response.lower() not in ["y", "yes"]:
                    self.stdout.write(self.style.WARNING("Operation cancelled"))
                    return

            self.stdout.write("Dropping existing places...")
            deleted_count = self._drop_existing_places(category_names)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully deleted {deleted_count} places")
            )
            # Exit after drop operation
            return

        # Normal import operation
        self.stdout.write(f"Importing OSM amenities from {region}...")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # 2. Get or download PBF file
        self.stdout.write("Locating PBF file...")
        pbf_path = self._get_or_download_pbf(region, data_dir)

        if not pbf_path.exists():
            self.stdout.write(self.style.ERROR(f"Failed to get PBF file for {region}"))
            return

        self.stdout.write(self.style.SUCCESS(f"PBF file: {pbf_path}"))

        # 3. Pre-filter PBF using osmium CLI
        force = options.get("force", False)
        self.stdout.write("Pre-filtering PBF with osmium tags-filter...")
        filtered_pbf = self._filter_pbf(pbf_path, category_names, force)

        if filtered_pbf is None:
            self.stdout.write(self.style.ERROR("Failed to create filtered PBF"))
            return

        # 4. Parse filtered PBF with location support for ways
        self.stdout.write("Parsing filtered OSM data...")
        handler = OSMHandler(category_names)

        # Apply with location handler for way centroid calculation
        idx = osmium.index.create_map("flex_mem")
        location_handler = osmium.NodeLocationsForWays(idx)
        location_handler.ignore_errors()
        osmium.apply(str(filtered_pbf), location_handler, handler)

        amenities = handler.amenities

        # Clean up filtered file
        filtered_pbf.unlink()

        self.stdout.write(f"Found {len(amenities)} amenities")

        if limit:
            amenities = amenities[:limit]
            self.stdout.write(f"Limited to {limit} amenities")

        # 5. Get or create OSM organization
        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={
                "name": "OpenStreetMap",
                "url": "https://www.openstreetmap.org",
                "is_active": True,
            },
        )

        # 6. Pre-cache categories and organizations to reduce DB queries
        self.stdout.write(
            "Pre-caching categories, organizations, and existing places..."
        )
        self._precache_data(amenities)

        # Initialize place lookup cache for deduplication performance
        self._place_cache = {}

        # PERFORMANCE: Pre-load all existing OSM associations for this region
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        osm_source_ids = {str(data["osm_id"]) for data in amenities}
        existing_associations = GeoPlaceSourceAssociation.objects.filter(
            organization=osm_org, source_id__in=osm_source_ids
        ).select_related("geo_place")

        for assoc in existing_associations:
            cache_key = f"osm_{assoc.source_id}"
            self._place_cache[cache_key] = assoc.geo_place

        self.stdout.write(f"Pre-loaded {len(self._place_cache)} existing associations")

        # 7. Upsert amenities
        self.stdout.write("Upserting amenities to database...")
        created_count = 0
        updated_count = 0
        skipped_count = 0

        # PERFORMANCE: Larger batch size for better performance
        batch_size = 500
        total_batches = (len(amenities) + batch_size - 1) // batch_size

        for batch_num, batch_start in enumerate(
            range(0, len(amenities), batch_size), 1
        ):
            batch_end = min(batch_start + batch_size, len(amenities))
            batch = amenities[batch_start:batch_end]

            if dry_run:
                for data in batch:
                    self.stdout.write(
                        f"[DRY RUN] Would upsert: {data['name'] or 'Unnamed'} "
                        f"({data['category_slug']}) at ({data['lat']}, {data['lon']})"
                    )
                continue

            # Process batch in single transaction
            try:
                with transaction.atomic():
                    for data in batch:
                        try:
                            result = self._upsert_amenity(data, osm_org, run_start)
                            if result == "created":
                                created_count += 1
                            elif result == "updated":
                                updated_count += 1
                            else:
                                skipped_count += 1
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"Error processing {data['name']}: {e}"
                                )
                            )

                # PERFORMANCE: Show progress with percentage and stats
                progress_pct = (batch_end / len(amenities)) * 100
                self.stdout.write(
                    f"[{batch_num}/{total_batches}] {batch_end}/{len(amenities)} "
                    f"({progress_pct:.1f}%) - Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}"
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error processing batch {batch_start}-{batch_end}: {e}"
                    )
                )

        # 8. Cleanup deleted places
        if not dry_run:
            self.stdout.write("Cleaning up deleted places...")
            deleted_count = self._cleanup_deleted_places(
                osm_org, run_start, category_names
            )
            self.stdout.write(f"Deactivated {deleted_count} places no longer in OSM")

        # Cleanup temp files
        if hasattr(self, "_cleanup_after") and self._cleanup_after:
            # Clean up PBF file
            if pbf_path.exists():
                pbf_path.unlink()
            # Remove temp directory
            if hasattr(self, "_storage_dir") and self._storage_dir.exists():
                try:
                    self._storage_dir.rmdir()
                except OSError:
                    pass  # Directory not empty, skip

        # Summary
        self.stdout.write(self.style.SUCCESS("\nImport complete!"))
        self.stdout.write(f"  Created: {created_count}")
        self.stdout.write(f"  Updated: {updated_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        if not dry_run:
            self.stdout.write(f"  Deactivated: {deleted_count}")

    def _get_or_download_pbf(self, region: str, data_dir: str | None) -> Path:
        """Get existing PBF file or download if not present."""
        # Determine storage directory
        if data_dir:
            storage_dir = Path(data_dir)
            storage_dir.mkdir(parents=True, exist_ok=True)
            cleanup_after = False  # Don't delete if using persistent dir
        else:
            storage_dir = Path(tempfile.mkdtemp())
            cleanup_after = True

        filename = f"{region.replace('/', '_')}.osm.pbf"
        pbf_path = storage_dir / filename

        # Check if file already exists
        if pbf_path.exists():
            file_size_mb = pbf_path.stat().st_size / (1024 * 1024)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Using cached PBF: {pbf_path} ({file_size_mb:.1f} MB)"
                )
            )
            self._cleanup_after = cleanup_after
            self._storage_dir = storage_dir
            return pbf_path

        # Download if not exists
        self.stdout.write("Downloading from Geofabrik...")
        url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"

        try:
            with httpx.stream(
                "GET", url, follow_redirects=True, timeout=300.0
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(pbf_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and downloaded % (1024 * 1024 * 10) == 0:  # Every 10MB
                            progress = (downloaded / total) * 100
                            self.stdout.write(f"  Progress: {progress:.1f}%")

            file_size_mb = pbf_path.stat().st_size / (1024 * 1024)
            self.stdout.write(
                self.style.SUCCESS(f"Downloaded: {pbf_path} ({file_size_mb:.1f} MB)")
            )
            self._cleanup_after = cleanup_after
            self._storage_dir = storage_dir
            return pbf_path

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Download failed: {e}"))
            if cleanup_after and storage_dir.exists():
                storage_dir.rmdir()
            return Path()

    def _upsert_amenity(
        self, data: dict, osm_org: Organization, run_start: datetime
    ) -> str:
        """Create or update GeoPlace + AmenityDetail."""
        source_id = str(data["osm_id"])  # OSM IDs are unique across nodes and ways
        location = Point(data["lon"], data["lat"])

        # Find existing place
        existing = self._find_existing_place(
            osm_org, source_id, location, data["category_slug"], data.get("brand")
        )

        if existing:
            # Update existing place
            self._update_place(existing, data, osm_org, source_id, run_start)
            return "updated"
        else:
            # Create new place
            self._create_place(data, osm_org, source_id, run_start, location)
            return "created"

    def _find_existing_place(
        self,
        osm_org: Organization,
        source_id: str,
        location: Point,
        category_slug: str,
        brand: str | None,
    ) -> GeoPlace | None:
        """Find existing GeoPlace using WEP008 deduplication logic."""
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        # 1. Check OSM source + source_id (OSM IDs are globally unique)
        # PERFORMANCE: Use cache to avoid repeated DB lookups
        cache_key = f"osm_{source_id}"
        if hasattr(self, "_place_cache") and cache_key in self._place_cache:
            return self._place_cache[cache_key]

        try:
            assoc = GeoPlaceSourceAssociation.objects.select_related("geo_place").get(
                organization=osm_org, source_id=source_id
            )
            place = assoc.geo_place
            if hasattr(self, "_place_cache"):
                self._place_cache[cache_key] = place
            return place
        except GeoPlaceSourceAssociation.DoesNotExist:
            pass

        # 2. Check location + category parent + brand (20m radius)
        # Different brands at same location = different places
        category_parent = category_slug.split(".")[0]

        # Get brand category if brand exists
        brand_category = None
        if brand:
            brand_category = self._get_or_create_brand_category(brand)

        try:
            nearby = GeoPlace.objects.filter(
                location__distance_lte=(location, 20),
                place_type__slug__startswith=category_parent,
                is_active=True,
            ).annotate(distance=Distance("location", location))

            # Filter by brand if provided
            if brand_category:
                nearby = nearby.filter(amenity_detail__brand=brand_category)
            else:
                # No brand specified - only match places without brand
                nearby = nearby.filter(amenity_detail__brand__isnull=True)

            nearby = nearby.order_by("distance")[
                :2
            ]  # PERFORMANCE: Limit to 2 instead of fetching all

            count = len(nearby)
            if count == 1:
                return nearby[0]
            elif count > 1:
                # Mark all for review
                nearby_ids = [p.id for p in nearby]
                GeoPlace.objects.filter(id__in=nearby_ids).update(
                    review_status="review"
                )
                return None
        except Exception:
            pass

        # 3. Check very small radius (4m) regardless of category or brand
        # Catches edge cases like wrong category or missing brand
        very_nearby = (
            GeoPlace.objects.filter(
                location__distance_lte=(location, 4),
                is_active=True,
            )
            .annotate(distance=Distance("location", location))
            .order_by("distance")[:2]  # PERFORMANCE: Limit to 2 instead of fetching all
        )

        very_nearby_list = list(very_nearby)
        if len(very_nearby_list) == 1:
            return very_nearby_list[0]
        elif len(very_nearby_list) > 1:
            nearby_ids = [p.id for p in very_nearby_list]
            GeoPlace.objects.filter(id__in=nearby_ids).update(review_status="review")
            return None

        return None

    def _create_place(
        self,
        data: dict,
        osm_org: Organization,
        source_id: str,
        run_start: datetime,
        location: Point,
    ):
        """Create new GeoPlace + AmenityDetail."""
        # Get or create category
        category = self._get_or_create_category(data["category_slug"])

        # Parse opening hours
        opening_hours_data = self._parse_opening_hours(data.get("opening_hours"))

        # Handle brand
        brand_category = None
        brand_org = None
        if data.get("brand"):
            brand_category = self._get_or_create_brand_category(data["brand"])
            brand_org = self._get_or_create_brand_organization(
                data["brand"], data.get("website")
            )

        # Create place
        place = GeoPlace.objects.create(
            name=data["name"] or "Unnamed",
            location=location,
            place_type=category,
            country_code=self._guess_country_code(location),
            detail_type="amenity",
            osm_tags=data["tags"],
            review_status="new",
        )

        # Create amenity detail
        AmenityDetail.objects.create(
            geo_place=place,
            operating_status="open",
            opening_hours=opening_hours_data,
            phones=self._format_phones(data.get("phone")),
            brand=brand_category,
        )

        # Create source association
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=osm_org,
            source_id=source_id,
            import_date=run_start,
            modified_date=run_start,
            priority=1,  # OSM has priority 1
        )

        # Handle website via ExternalLink
        if data.get("website"):
            # Use brand organization if brand matches website
            source_org = None
            if brand_org and data.get("brand") and data.get("website"):
                brand_lower = data["brand"].lower()
                website_lower = data["website"].lower()
                if brand_lower in website_lower:
                    source_org = brand_org

            self._add_external_link(place, data["website"], "website", source_org)

        # Add OSM edit link via MapComplete
        osm_edit_url = self._create_mapcomplete_url(data)
        if osm_edit_url:
            mapcomplete_org = self._get_or_create_mapcomplete_organization()
            self._add_external_link(
                place, osm_edit_url, "osm_edit", mapcomplete_org, data["name"]
            )

    def _update_place(
        self,
        place: GeoPlace,
        data: dict,
        osm_org: Organization,
        source_id: str,
        run_start: datetime,
    ):
        """Update existing GeoPlace + AmenityDetail."""
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        # Update fields not in protected_fields
        protected = place.protected_fields or ["name", "location"]

        if "name" not in protected and data["name"]:
            place.name = data["name"]
        if "location" not in protected:
            place.location = Point(data["lon"], data["lat"])

        place.osm_tags = data["tags"]
        place.save()

        # Update AmenityDetail
        if hasattr(place, "amenity_detail"):
            detail = place.amenity_detail
            if data.get("opening_hours"):
                detail.opening_hours = self._parse_opening_hours(data["opening_hours"])
            if data.get("phone"):
                detail.phones = self._format_phones(data["phone"])
            if data.get("brand"):
                detail.brand = self._get_or_create_brand_category(data["brand"])
            detail.save()

        # Update source association
        assoc, created = GeoPlaceSourceAssociation.objects.update_or_create(
            geo_place=place,
            organization=osm_org,
            defaults={
                "source_id": source_id,
                "modified_date": run_start,
            },
        )

        # Handle website via ExternalLink
        if data.get("website"):
            # Use brand organization if brand matches website
            source_org = None
            if data.get("brand") and data.get("website"):
                brand_lower = data["brand"].lower()
                website_lower = data["website"].lower()
                if brand_lower in website_lower:
                    brand_org = self._get_or_create_brand_organization(
                        data["brand"], data["website"]
                    )
                    source_org = brand_org

            self._add_external_link(place, data["website"], "website", source_org)

        # Add OSM edit link via MapComplete
        osm_edit_url = self._create_mapcomplete_url(data)
        if osm_edit_url:
            mapcomplete_org = self._get_or_create_mapcomplete_organization()
            self._add_external_link(
                place, osm_edit_url, "osm_edit", mapcomplete_org, data["name"]
            )

    def _cleanup_deleted_places(
        self, osm_org: Organization, run_start: datetime, category_names: list[str]
    ) -> int:
        """Deactivate places not seen in this import run."""
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        # Get categories for this import
        category_slugs = set()
        for cat in get_categories(category_names):
            for mapping in cat.mappings:
                parts = mapping.category_slug.split(".")
                child_slug = parts[1] if len(parts) > 1 else parts[0]
                category_slugs.add(child_slug)

        # Get all categories with these parent slugs
        categories = Category.objects.filter(slug__in=category_slugs)

        # PERFORMANCE: Use bulk update instead of iterating
        stale_place_ids = GeoPlaceSourceAssociation.objects.filter(
            organization=osm_org,
            modified_date__lt=run_start,
            geo_place__place_type__in=categories,
            geo_place__is_active=True,
        ).values_list("geo_place_id", flat=True)

        stale_place_ids_list = list(stale_place_ids)

        if stale_place_ids_list:
            count = GeoPlace.objects.filter(id__in=stale_place_ids_list).update(
                is_active=False, review_status="review"
            )
        else:
            count = 0

        return count

    def _count_places(self, category_names: list[str]) -> int:
        """Count existing places with specified categories from OSM."""
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        # Get OSM organization
        try:
            osm_org = Organization.objects.get(slug="osm")
        except Organization.DoesNotExist:
            return 0

        # Get all category slugs
        category_slugs = set()
        for cat in get_categories(category_names):
            for mapping in cat.mappings:
                parts = mapping.category_slug.split(".")
                child_slug = parts[1] if len(parts) > 1 else parts[0]
                category_slugs.add(child_slug)

        # Find all categories with these slugs
        categories = Category.objects.filter(slug__in=category_slugs)

        if not categories.exists():
            return 0

        # Count places with these categories from OSM source
        count = (
            GeoPlaceSourceAssociation.objects.filter(
                organization=osm_org,
                geo_place__place_type__in=categories,
            )
            .values("geo_place")
            .distinct()
            .count()
        )

        return count

    def _drop_existing_places(self, category_names: list[str]) -> int:
        """Drop all existing places with specified categories."""
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        # Get OSM organization
        try:
            osm_org = Organization.objects.get(slug="osm")
        except Organization.DoesNotExist:
            self.stdout.write(self.style.WARNING("OSM organization not found"))
            return 0

        # Get all category slugs
        category_slugs = set()
        for cat in get_categories(category_names):
            for mapping in cat.mappings:
                parts = mapping.category_slug.split(".")
                child_slug = parts[1] if len(parts) > 1 else parts[0]
                category_slugs.add(child_slug)

        # Find all categories with these slugs
        categories = Category.objects.filter(slug__in=category_slugs)

        if not categories.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"No categories found with slugs: {', '.join(category_slugs)}"
                )
            )
            return 0

        self.stdout.write(f"Found {categories.count()} categories to filter by")

        # Find all places with these categories from OSM source
        place_ids = (
            GeoPlaceSourceAssociation.objects.filter(
                organization=osm_org,
                geo_place__place_type__in=categories,
            )
            .values_list("geo_place_id", flat=True)
            .distinct()
        )

        place_ids_list = list(place_ids)
        count = len(place_ids_list)

        if count == 0:
            return 0

        # Delete the places using bulk delete (cascade will handle associations)
        deleted, _ = GeoPlace.objects.filter(id__in=place_ids_list).delete()

        return count

    def _precache_data(self, amenities: list[dict]):
        """Pre-cache categories, brands, and organizations to reduce DB queries."""
        # Cache for categories
        self._category_cache = {}
        self._brand_cache = {}
        self._brand_org_cache = {}

        # Collect unique category slugs and brands
        category_slugs = set()
        brands = set()

        for data in amenities:
            category_slugs.add(data["category_slug"])
            if data.get("brand"):
                brands.add(data["brand"].lower())

        # Pre-create all categories
        for category_slug in category_slugs:
            try:
                self._category_cache[category_slug] = self._get_or_create_category(
                    category_slug
                )
            except Exception:
                pass

        # Pre-create brand parent category
        if brands:
            brand_parent, _ = Category.objects.get_or_create(
                slug="brand",
                defaults={"name": "Brand"},
            )

            # Pre-create all brand categories and organizations
            for brand_name in brands:
                brand_slug = brand_name.replace(" ", "_")
                try:
                    brand_category, _ = Category.objects.get_or_create(
                        slug=brand_slug,
                        defaults={
                            "name": brand_name.title(),
                            "parent": brand_parent,
                        },
                    )
                    self._brand_cache[brand_name] = brand_category
                except Exception:
                    pass

        self.stdout.write(
            f"Cached {len(self._category_cache)} categories and {len(self._brand_cache)} brands"
        )

    def _get_or_create_brand_category(self, brand_name: str) -> Category:
        """Get or create brand category (cached)."""
        brand_name_lower = brand_name.lower()

        # Check cache first
        if hasattr(self, "_brand_cache") and brand_name_lower in self._brand_cache:
            return self._brand_cache[brand_name_lower]

        # Fallback to DB query if not cached
        parent, _ = Category.objects.get_or_create(
            slug="brand",
            defaults={
                "name": "Brand",
            },
        )

        brand_slug = brand_name_lower.replace(" ", "_")[:50]  # Limit to 50 chars

        brand_category, _ = Category.objects.get_or_create(
            slug=brand_slug,
            defaults={
                "name": brand_name.title(),
                "parent": parent,
            },
        )

        # Cache for future use
        if hasattr(self, "_brand_cache"):
            self._brand_cache[brand_name_lower] = brand_category

        return brand_category

    def _get_or_create_mapcomplete_organization(self) -> Organization:
        """Get or create MapComplete organization."""
        org, _ = Organization.objects.get_or_create(
            slug="mapcomplete",
            defaults={
                "name": "MapComplete",
                "url": "https://mapcomplete.org",
                "is_active": True,
            },
        )
        return org

    def _get_or_create_brand_organization(
        self, brand_name: str, website: str | None
    ) -> Organization:
        """Get or create organization for brand (cached)."""
        brand_slug = brand_name.lower().replace(" ", "_")[:50]  # Limit to 50 chars

        # Check cache first
        if hasattr(self, "_brand_org_cache") and brand_slug in self._brand_org_cache:
            return self._brand_org_cache[brand_slug]

        # Extract base URL from website if available
        url = None
        if website:
            # Extract domain from URL (e.g., https://www.volg.ch/... -> https://www.volg.ch)
            from urllib.parse import urlparse

            parsed = urlparse(website)
            url = f"{parsed.scheme}://{parsed.netloc}"

        org, _ = Organization.objects.get_or_create(
            slug=brand_slug,
            defaults={
                "name": brand_name.title(),
                "url": url or "",
                "is_active": True,
            },
        )

        # Update URL if it was empty and we have one now
        if not org.url and url:
            org.url = url
            org.save(update_fields=["url"])

        # Cache for future use
        if hasattr(self, "_brand_org_cache"):
            self._brand_org_cache[brand_slug] = org

        return org

    def _get_or_create_category(self, category_slug: str) -> Category:
        """Get or create category by identifier (parent.slug format)."""
        # Check cache first
        if hasattr(self, "_category_cache") and category_slug in self._category_cache:
            return self._category_cache[category_slug]

        # Use identifier field for lookup - much simpler!
        # identifier format: "root.slug" or "parent.slug"
        # Our category_slug format: "slug" or "parent.slug"
        # Need to handle: category_slug="restaurant" should match identifier="root.restaurant"
        parts = category_slug.split(".")

        if len(parts) == 1:
            # Root category: "restaurant" -> identifier="root.restaurant"
            identifier = f"root.{parts[0]}"
            parent = None
            slug = parts[0]
        else:
            # Child category: "restaurant.cafe" -> identifier="restaurant.cafe"
            identifier = category_slug
            parent_slug = parts[0]
            slug = parts[1]

            # Ensure parent exists
            parent, _ = Category.objects.get_or_create(
                slug=parent_slug,
                parent=None,
                defaults={"name": parent_slug.replace("_", " ").title()},
            )

        # Try to get by identifier (most efficient)
        try:
            category = Category.objects.get(identifier=identifier)
        except Category.DoesNotExist:
            # Create new category
            category = Category.objects.create(
                slug=slug,
                parent=parent,
                name=slug.replace("_", " ").title(),
            )
        except Category.MultipleObjectsReturned:
            # Data inconsistency - use first match
            category = Category.objects.filter(identifier=identifier).first()

        # Cache for future use
        if hasattr(self, "_category_cache"):
            self._category_cache[category_slug] = category

        return category

    def _parse_opening_hours(self, opening_hours_str: str | None) -> dict:
        """Parse OSM opening_hours format to our JSON schema."""
        if not opening_hours_str:
            return {}

        try:
            from opening_hours import OpeningHours
            from datetime import datetime, timedelta

            oh = OpeningHours(opening_hours_str)

            # Convert to our weekly format
            result = {}
            weekdays = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]

            # Get a reference date (use current week)
            today = datetime.now()
            start_of_week = today - timedelta(days=today.weekday())

            for i, weekday in enumerate(weekdays):
                day_date = start_of_week + timedelta(days=i)

                # Get intervals for this day
                intervals = []
                try:
                    # Check if open at various times throughout the day
                    # Sample every 30 minutes to find open periods
                    current_time = day_date.replace(hour=0, minute=0, second=0)
                    end_time = day_date.replace(hour=23, minute=59, second=59)

                    in_open_period = False
                    period_start = None

                    while current_time <= end_time:
                        is_open = oh.is_open(current_time)

                        if is_open and not in_open_period:
                            # Start of open period
                            in_open_period = True
                            period_start = current_time.strftime("%H:%M")
                        elif not is_open and in_open_period:
                            # End of open period
                            in_open_period = False
                            intervals.append(
                                {
                                    "open": period_start,
                                    "close": current_time.strftime("%H:%M"),
                                }
                            )

                        current_time += timedelta(minutes=30)

                    # Close any open period at end of day
                    if in_open_period:
                        intervals.append({"open": period_start, "close": "23:59"})

                except Exception:
                    # If parsing fails for this day, skip it
                    pass

                if intervals:
                    result[weekday] = intervals

            # Store raw string for reference
            if result:
                result["_raw"] = opening_hours_str
            else:
                # If parsing produced no results, just store raw
                result = {"_raw": opening_hours_str}

            return result

        except Exception:
            # Fallback: store raw string
            return {"_raw": opening_hours_str}

    def _format_phones(self, phone: str | None) -> list:
        """Format phone number(s) to our JSON schema."""
        if not phone:
            return []

        # Split multiple phone numbers (some OSM entries have multiple separated by ;)
        phones = [p.strip() for p in phone.split(";") if p.strip()]

        return [{"number": p} for p in phones]

    def _guess_country_code(self, location: Point) -> str:
        """Guess country code from location (simplified for now)."""
        # TODO: Implement proper country lookup via shapefile or API
        # For now, return a default - this should be improved
        return "CH"  # Default to Switzerland for testing

    def _create_mapcomplete_url(self, data: dict) -> str | None:
        """Create MapComplete edit URL based on OSM element and category."""
        osm_type = data.get("osm_type")
        osm_id = data.get("osm_id")
        theme = data.get("mapcomplete_theme", "shops")

        if not osm_type or not osm_id:
            return None

        # Build MapComplete URL
        # Format: https://mapcomplete.org/{theme}.html#{osm_type}/{osm_id}
        url = f"https://mapcomplete.org/{theme}.html#{osm_type}/{osm_id}"

        return url

    def _filter_pbf(
        self, pbf_path: Path, category_names: list[str], force: bool = False
    ) -> Path:
        """Pre-filter PBF file using osmium tags-filter CLI for performance.

        Extracts all tags from osm_filters and creates osmium filter expressions.
        Uses OR logic for all tags (just pre-filtering, exact matching happens in handler).

        Args:
            pbf_path: Path to input PBF file
            category_names: List of category names to filter
            force: If True, overwrite existing filtered file without asking
        """
        from collections import defaultdict
        import subprocess

        # Check if filtered file already exists
        filtered_pbf = pbf_path.parent / f"{pbf_path.stem}_filtered.osm.pbf"

        if filtered_pbf.exists():
            file_size_mb = filtered_pbf.stat().st_size / (1024 * 1024)
            if force:
                self.stdout.write(
                    f"Overwriting existing filtered file: {filtered_pbf} ({file_size_mb:.1f} MB)"
                )
                filtered_pbf.unlink()
            else:
                self.stdout.write(
                    f"Using existing filtered file: {filtered_pbf} ({file_size_mb:.1f} MB)"
                )
                self.stdout.write("Use --force to regenerate the filtered file")
                return filtered_pbf

        # Collect all tags from all category mappings
        pre_filter_tags = defaultdict(set)

        categories = get_categories(category_names)
        for cat in categories:
            for mapping in cat.mappings:
                for filter_item in mapping.osm_filters:
                    # Handle tuple (OR case) - extract all tags
                    if isinstance(filter_item, tuple):
                        for tag in filter_item:
                            if "=" in tag:
                                key, value = tag.split("=", 1)
                                pre_filter_tags[key].add(value)
                            else:
                                # Key-only filter
                                pre_filter_tags[tag]  # Creates empty set
                    # Handle string
                    elif isinstance(filter_item, str):
                        if "=" in filter_item:
                            key, value = filter_item.split("=", 1)
                            pre_filter_tags[key].add(value)
                        else:
                            # Key-only filter
                            pre_filter_tags[filter_item]  # Creates empty set

        # Build osmium filter expressions
        # Format: nw/key or nw/key=value1,value2
        filter_expressions = []
        for key, values in pre_filter_tags.items():
            if values:
                # Key with specific values
                values_str = ",".join(sorted(values))
                filter_expressions.append(f"nw/{key}={values_str}")
            else:
                # Key-only filter
                filter_expressions.append(f"nw/{key}")

        if not filter_expressions:
            self.stdout.write(self.style.WARNING("No filter expressions generated"))
            return None

        # Build osmium command
        cmd = (
            ["osmium", "tags-filter", str(pbf_path)]
            + filter_expressions
            + ["-o", str(filtered_pbf)]
        )

        self.stdout.write(
            f"Running: osmium tags-filter with {len(filter_expressions)} expressions"
        )

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stderr:
                self.stdout.write(result.stderr)
            return filtered_pbf
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"osmium tags-filter failed: {e}"))
            self.stdout.write(self.style.ERROR(f"stderr: {e.stderr}"))
            return None

    def _add_external_link(
        self,
        place: GeoPlace,
        url: str,
        link_type: str,
        source_org: Organization | None = None,
        place_name: str | None = None,
    ):
        """Add external link to place via ExternalLink model."""
        from server.apps.external_links.models import ExternalLink

        # Get or create parent category (link_type)
        parent_category, _ = Category.objects.get_or_create(
            slug="link_type",
            defaults={"name": "Link Type"},
        )

        # Get or create link_type category (e.g., "website", "osm_edit")
        link_type_category, _ = Category.objects.get_or_create(
            slug=link_type,
            defaults={
                "name": link_type.replace("_", " ").title(),
                "parent": parent_category,
            },
        )

        # Prepare label and description based on link type
        if link_type == "osm_edit":
            label_en = "Edit"
            label_de = "Bearbeiten"
            label_fr = "Modifier"
            label_it = "Modifica"
            name = place_name or place.name or "this place"
            description_en = f"Edit '{name}' on MapComplete.org"
            description_de = f"'{name}' auf MapComplete.org bearbeiten"
            description_fr = f"Modifier '{name}' sur MapComplete.org"
            description_it = f"Modifica '{name}' su MapComplete.org"
        else:
            label_en = place.name
            label_de = place.name
            label_fr = place.name
            label_it = place.name
            description_en = ""
            description_de = ""
            description_fr = ""
            description_it = ""

        # Try to get existing link first
        try:
            external_link = ExternalLink.objects.get(url=url)
            created = False
        except ExternalLink.DoesNotExist:
            # Create new link with health check disabled for bulk import performance
            external_link = ExternalLink(
                url=url,
                label_en=label_en,
                label_de=label_de,
                label_fr=label_fr,
                label_it=label_it,
                description_en=description_en,
                description_de=description_de,
                description_fr=description_fr,
                description_it=description_it,
                link_type=link_type_category,
                source=source_org,
            )
            external_link.save(skip_health_check=True)
            created = True

        # Update source if it was empty and we have one now
        if not created and not external_link.source and source_org:
            external_link.source = source_org
            external_link.save(update_fields=["source"], skip_health_check=True)

        # Associate with place
        from server.apps.geometries.models import GeoPlaceExternalLink

        GeoPlaceExternalLink.objects.get_or_create(
            geo_place=place,
            external_link=external_link,
        )
