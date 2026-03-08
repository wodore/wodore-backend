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
from dataclasses import dataclass
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

# Global Overpass server list with labels for display
OVERPASS_SERVERS = [
    ("A", "https://overpass.private.coffee/api/interpreter"),
    ("B", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"),
    ("C", "https://overpass-api.de/api/interpreter"),
]


@dataclass
class OSMElement:
    """Unified schema for OSM elements from both JSON and XML diff responses."""

    osm_id: str  # e.g., "node/123456" or "way/789"
    osm_type: str  # "node" or "way"
    lat: float
    lon: float
    tags: dict
    action: (
        str | None
    )  # "create", "modify", "delete" for diff mode; None for full import
    version: int = 0  # OSM version number
    timestamp: str = ""  # OSM timestamp


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
        parser.add_argument(
            "--overpass",
            action="store_true",
            help="Use Overpass API instead of PBF files (region must be country code like CH, AT, DE)",
        )
        parser.add_argument(
            "--overpass-server",
            type=str,
            default=None,
            help="Overpass API server URL (default: use built-in pool). Useful for parallel runs with different servers.",
        )
        parser.add_argument(
            "-w",
            "--workers",
            type=int,
            default=1,
            help="Number of parallel workers (default: 1). Each worker processes one mapping at a time using a different Overpass server.",
        )
        parser.add_argument(
            "--overpass-queries",
            type=str,
            help="Write all Overpass queries to a markdown file (for debugging)",
        )
        parser.add_argument(
            "--since",
            type=str,
            help="Only fetch elements modified since timestamp (ISO format: 2026-03-08T00:00:00Z) or 'auto' to use last import timestamp",
        )
        parser.add_argument(
            "--state-file",
            type=str,
            default=None,
            help="Path to state JSON file for tracking per-mapping timestamps (default: <data-dir>/.geoplaces_osm_import.json)",
        )

    def handle(self, *args, **options):
        """Main command execution."""
        region = options["region"]
        dry_run = options["dry_run"]
        limit = options.get("limit")
        data_dir = options.get("data_dir")
        drop = options.get("drop", False)
        force = options.get("force", False)
        use_overpass = options.get("overpass", False)
        overpass_server = options.get("overpass_server")
        overpass_queries_file = options.get("overpass_queries")
        since = options.get("since")
        state_file_path = options.get("state_file")
        run_start = timezone.now()

        # Determine state file location
        if state_file_path:
            state_file = Path(state_file_path)
        else:
            state_file = Path(data_dir or ".") / ".geoplaces_osm_import.json"

        # Load state for --since auto support
        state = self._load_state(state_file)

        # Handle --since auto: use last import timestamp from state
        # For now, use global timestamp (later we can use per-mapping timestamps)
        if since == "auto":
            # Try to get the most recent timestamp from any mapping in this country
            country_state = state.get("countries", {}).get(region.upper(), {})
            mappings_state = country_state.get("mappings", {})
            if mappings_state:
                # Get the most recent timestamp across all mappings
                timestamps = [
                    m["last_import"]
                    for m in mappings_state.values()
                    if "last_import" in m
                ]
                if timestamps:
                    since = max(timestamps)  # Use most recent
                    self.stdout.write(f"Using --since auto: {since}")
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"No previous import timestamp found in {state_file}, importing all data"
                        )
                    )
                    since = None
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"No previous import found for {region} in {state_file}, importing all data"
                    )
                )
                since = None

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

        # 2. Fetch amenities (either via Overpass API or PBF file)
        if use_overpass:
            # Get or create OSM organization
            osm_org, _ = Organization.objects.get_or_create(
                slug="osm",
                defaults={
                    "name": "OpenStreetMap",
                    "url": "https://www.openstreetmap.org",
                    "is_active": True,
                },
            )

            # Initialize place lookup cache for deduplication performance
            self._place_cache = {}

            # Get workers parameter
            workers = options.get("workers", 1)

            # Process each category/mapping in a pipeline (fetch → process → import)
            if workers > 1:
                # Use parallel processing
                self._process_overpass_parallel(
                    region=region,
                    category_names=category_names,
                    osm_org=osm_org,
                    run_start=run_start,
                    workers=workers,
                    limit=limit,
                    overpass_server=overpass_server,
                    overpass_queries_file=overpass_queries_file,
                    since=since,
                    dry_run=dry_run,
                    state=state,
                    state_file=state_file,
                )
                success = True
            else:
                # Use sequential processing
                success = self._process_overpass_pipeline(
                    region=region,
                    category_names=category_names,
                    osm_org=osm_org,
                    run_start=run_start,
                    limit=limit,
                    overpass_server=overpass_server,
                    overpass_queries_file=overpass_queries_file,
                    since=since,
                    dry_run=dry_run,
                    state=state,
                    state_file=state_file,
                )

            if not success:
                self.stdout.write(
                    self.style.ERROR("Failed to process Overpass API data")
                )
                return

            # Get stats from instance variables set by pipeline
            created_count = getattr(self, "_pipeline_created", 0)
            updated_count = getattr(self, "_pipeline_updated", 0)
            skipped_count = getattr(self, "_pipeline_skipped", 0)
            deleted_count = getattr(self, "_pipeline_deleted", 0)
            error_count = getattr(self, "_pipeline_errors", 0)

            # Cleanup deleted places (skip if using --since or --limit as it's a partial import)
            # Note: If using diff mode (--since), deletions are already handled via action="delete"
            if not dry_run and not since and not limit:
                self.stdout.write("\nCleaning up deleted places...")
                cleanup_deleted_count = self._cleanup_deleted_places(
                    osm_org, run_start, category_names, region
                )
                deleted_count += cleanup_deleted_count
                self.stdout.write(
                    f"Deactivated {cleanup_deleted_count} places no longer in OSM"
                )
            else:
                if since or limit:
                    self.stdout.write(
                        "\n[Skipping cleanup - partial import with --since or --limit]"
                    )

            # Save state with per-mapping timestamps
            if not dry_run:
                # Update state for all processed mappings
                # Note: Individual mapping counts will be updated by the worker/pipeline
                # Here we just ensure the file is saved
                self._save_state(state_file, state)
                self.stdout.write(f"Saved import state to: {state_file}")

            # Summary
            if error_count > 0:
                self.stdout.write(self.style.WARNING("\nImport completed with errors!"))
            else:
                self.stdout.write(self.style.SUCCESS("\nImport complete!"))

            self.stdout.write(f"  Created: {created_count}")
            self.stdout.write(f"  Updated: {updated_count}")
            self.stdout.write(f"  Skipped: {skipped_count}")
            if error_count > 0:
                self.stdout.write(self.style.ERROR(f"  Errors: {error_count}"))
            if not dry_run:
                self.stdout.write(f"  Deactivated: {deleted_count}")

            return
        else:
            # PBF approach
            self.stdout.write("Locating PBF file...")
            pbf_path = self._get_or_download_pbf(region, data_dir)

            if not pbf_path.exists():
                self.stdout.write(
                    self.style.ERROR(f"Failed to get PBF file for {region}")
                )
                return

            self.stdout.write(self.style.SUCCESS(f"PBF file: {pbf_path}"))

            # Pre-filter PBF using osmium CLI
            self.stdout.write("Pre-filtering PBF with osmium tags-filter...")
            filtered_pbf = self._filter_pbf(pbf_path, category_names, force)

            if filtered_pbf is None:
                self.stdout.write(self.style.ERROR("Failed to create filtered PBF"))
                return

            # Parse filtered PBF with location support for ways
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

        # Build source_ids in OSM_TYPE/OSM_ID format for lookup
        osm_source_ids = {f"{data['osm_type']}/{data['osm_id']}" for data in amenities}
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

        # Save state for --since auto if using Overpass
        if use_overpass and not dry_run:
            self._save_state(state_file, state)
            self.stdout.write(f"Saved import state to: {state_file}")

        # Summary
        self.stdout.write(self.style.SUCCESS("\nImport complete!"))
        self.stdout.write(f"  Created: {created_count}")
        self.stdout.write(f"  Updated: {updated_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        if not dry_run:
            self.stdout.write(f"  Deactivated: {deleted_count}")

    def _load_state(self, state_file: Path) -> dict:
        """Load import state from JSON file.

        Returns dict with structure:
        {
            "countries": {
                "CH": {
                    "mappings": {
                        "groceries.supermarket": {
                            "last_import": "2026-03-08T10:30:00Z",
                            "last_count": 1234
                        }
                    }
                }
            }
        }
        """
        if state_file.exists():
            import json

            try:
                with open(state_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # Return empty state if file is corrupted
                return {"countries": {}}
        return {"countries": {}}

    def _save_state(self, state_file: Path, state: dict) -> None:
        """Save import state to JSON file."""
        import json

        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _update_mapping_state(
        self,
        state: dict,
        country: str,
        mapping_slug: str,
        timestamp: str,
        count: int = 0,
    ) -> None:
        """Update state for a specific country/mapping combination."""
        country = country.upper()

        if country not in state["countries"]:
            state["countries"][country] = {"mappings": {}}

        if "mappings" not in state["countries"][country]:
            state["countries"][country]["mappings"] = {}

        state["countries"][country]["mappings"][mapping_slug] = {
            "last_import": timestamp,
            "last_count": count,
        }

    def _get_mapping_timestamp(
        self, state: dict, country: str, mapping_slug: str
    ) -> str | None:
        """Get last import timestamp for a specific country/mapping."""
        country = country.upper()
        try:
            return state["countries"][country]["mappings"][mapping_slug]["last_import"]
        except KeyError:
            return None

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
        # Save source_id as OSM_TYPE/OSM_ID format to ensure uniqueness
        source_id = (
            f"{data['osm_type']}/{data['osm_id']}"  # e.g., "node/123456", "way/789"
        )
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
        """Find existing GeoPlace using WEP008 deduplication logic.

        PERFORMANCE OPTIMIZATIONS:
        - Filters by country_code to use composite spatial index
        - Caches OSM source_id lookups
        - Limits results to avoid fetching large result sets
        """
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

        # Get current country for spatial index optimization
        country_code = getattr(self, "_current_region", "CH")

        # 2. Check location + category parent + brand (20m radius)
        # Different brands at same location = different places
        category_parent = category_slug.split(".")[0]

        # Get brand category if brand exists
        brand_category = None
        if brand:
            brand_category = self._get_or_create_brand_category(brand)

        try:
            # PERFORMANCE: Use distance_lte + country filter to leverage composite GIST index
            # Note: For SRID 4326 (lat/lon), we must use distance_lte, not dwithin
            nearby = GeoPlace.objects.filter(
                country_code=country_code,  # Uses composite index
                is_active=True,
                location__distance_lte=(
                    location,
                    20,
                ),  # 20 meters - PostGIS handles conversion
                place_type__slug__startswith=category_parent,
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
        # PERFORMANCE: Use distance_lte + country filter for bbox optimization
        very_nearby = (
            GeoPlace.objects.filter(
                country_code=country_code,  # Uses composite index
                is_active=True,
                location__distance_lte=(
                    location,
                    4,
                ),  # 4 meters - PostGIS handles conversion
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

        # Extract multilingual names and descriptions
        name_i18n = self._extract_i18n_field(data["tags"], "name")
        description_i18n = self._extract_i18n_field(data["tags"], "description")

        # Create place with i18n support
        # Base fields use Django's LANGUAGE_CODE (de)
        # Other languages use field_LANG_CODE suffix (name_en, name_fr, etc.)
        from django.conf import settings

        place_data = {
            "name": name_i18n.get(settings.LANGUAGE_CODE, "Unnamed"),
            "location": location,
            "place_type": category,
            "country_code": self._guess_country_code(location),
            "detail_type": "amenity",
            "osm_tags": data["tags"],
            "review_status": "new",
        }

        # Add translations for non-default languages
        for lang_code, name_value in name_i18n.items():
            if lang_code != settings.LANGUAGE_CODE:
                place_data[f"name_{lang_code}"] = name_value

        # Add default description
        if settings.LANGUAGE_CODE in description_i18n:
            place_data["description"] = description_i18n[settings.LANGUAGE_CODE]

        # Add description translations for non-default languages
        for lang_code, desc_value in description_i18n.items():
            if lang_code != settings.LANGUAGE_CODE and desc_value:
                place_data[f"description_{lang_code}"] = desc_value

        place = GeoPlace.objects.create(**place_data)

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
            extra={
                "osm_type": data["osm_type"],  # node, way, or relation
                "osm_id": data["osm_id"],  # numeric ID
            },
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

        # Reactivate if previously deactivated (place was deleted but now exists again in OSM)
        if not place.is_active:
            place.is_active = True
            place.review_status = "review"  # Reset review status for reactivated places

        # Update fields not in protected_fields
        protected = place.protected_fields or ["name", "location"]

        # Extract multilingual names and descriptions
        name_i18n = self._extract_i18n_field(data["tags"], "name")
        description_i18n = self._extract_i18n_field(data["tags"], "description")

        from django.conf import settings

        # Update name (default language and translations)
        if "name" not in protected:
            # Update base field (default language)
            if settings.LANGUAGE_CODE in name_i18n:
                place.name = name_i18n[settings.LANGUAGE_CODE]
            # Update translations for non-default languages
            for lang_code, name_value in name_i18n.items():
                if lang_code != settings.LANGUAGE_CODE:
                    setattr(place, f"name_{lang_code}", name_value)

        # Update description (default language and translations)
        if "description" not in protected:
            # Update base field (default language)
            if settings.LANGUAGE_CODE in description_i18n:
                place.description = description_i18n[settings.LANGUAGE_CODE]
            # Update translations for non-default languages
            for lang_code, desc_value in description_i18n.items():
                if lang_code != settings.LANGUAGE_CODE and desc_value:
                    setattr(place, f"description_{lang_code}", desc_value)

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
                "extra": {
                    "osm_type": data["osm_type"],  # node, way, or relation
                    "osm_id": data["osm_id"],  # numeric ID
                },
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

    def _deactivate_by_osm_id(self, osm_id: str, osm_org: Organization) -> bool:
        """Deactivate a place by its OSM ID.

        Args:
            osm_id: OSM ID in format "node/123456" or "way/789"
            osm_org: OSM organization

        Returns:
            True if place was deactivated, False if not found or already inactive
        """
        from server.apps.geometries.models import GeoPlaceSourceAssociation

        try:
            # Find the place by OSM ID
            association = GeoPlaceSourceAssociation.objects.select_related(
                "geo_place"
            ).get(
                organization=osm_org,
                source_id=osm_id,
            )

            # Only deactivate if currently active
            if association.geo_place.is_active:
                association.geo_place.is_active = False
                association.geo_place.review_status = "review"
                association.geo_place.save(update_fields=["is_active", "review_status"])
                return True

            return False
        except GeoPlaceSourceAssociation.DoesNotExist:
            # Place not in database
            return False

    def _cleanup_deleted_places(
        self,
        osm_org: Organization,
        run_start: datetime,
        category_names: list[str],
        region: str,
    ) -> int:
        """Deactivate places not seen in this import run.

        Args:
            region: Country code (e.g., "CH", "FR") to limit cleanup to specific country
        """
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
        # Filter by country code to only deactivate places in the imported region
        country_code = region.upper()
        stale_place_ids = GeoPlaceSourceAssociation.objects.filter(
            organization=osm_org,
            modified_date__lt=run_start,
            geo_place__place_type__in=categories,
            geo_place__country_code=country_code,
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

    def _extract_i18n_field(self, tags: dict, field_name: str) -> dict:
        """
        Extract multilingual field from OSM tags.

        OSM uses format:
            name         = Default/local name
            name:de      = German name
            name:en      = English name
            name:fr      = French name
            name:it      = Italian name

        Returns:
            Dict with language codes as keys
            The Django default language (LANGUAGE_CODE='de') is used for the base field
            Example: {'de': 'Zermatt', 'fr': 'Cervin', 'it': 'Cervino', 'en': 'Matterhorn'}
        """
        from django.conf import settings

        result = {}

        # Get language-specific values for all configured languages
        for lang_code in settings.LANGUAGE_CODES:
            key = f"{field_name}:{lang_code}"
            if key in tags:
                result[lang_code] = tags[key]

        # If no language-specific value exists for the default language,
        # use the generic field value (name -> de if LANGUAGE_CODE='de')
        if settings.LANGUAGE_CODE not in result:
            default_value = tags.get(field_name, "")
            if default_value:
                result[settings.LANGUAGE_CODE] = default_value

        return result

    def _guess_country_code(self, location: Point) -> str:
        """Get country code from current import region.

        Uses the region parameter from the import command (e.g., "CH", "FR").
        Falls back to "CH" if not set (for backwards compatibility).
        """
        return getattr(self, "_current_region", "CH")

    def _process_mapping_worker(
        self,
        worker_id: int,
        mapping_data: tuple,
        region: str,
        osm_org: Organization,
        run_start: datetime,
        category_names: list[str],
        api_endpoint: str | None,
        headers: dict,
        queries_md: dict,
        since: datetime | None,
        limit: int | None,
        dry_run: bool,
        console,
        progress,
        overall_task,
    ) -> dict:
        """Worker function to process a single mapping in parallel.

        Returns a dict with:
            - created: int
            - updated: int
            - skipped: int
            - download_bytes: int
            - server_label: str
            - success: bool
        """
        from django.db import connection

        category, mapping = mapping_data

        # Calculate server start index based on worker_id
        server_start_index = worker_id % len(OVERPASS_SERVERS)

        # Create task for this mapping
        server_letter = OVERPASS_SERVERS[server_start_index][0]
        task_id = progress.add_task(
            f"worker_{worker_id}",
            total=3,  # 3 stages: fetch, process, import
            mapping=f"{mapping.category_slug}",
            status=f"[yellow]fetching from {server_letter}...[/yellow]",
        )

        try:
            # PIPELINE STAGE 1: FETCH
            elements, download_size, server_label, element_count = (
                self._fetch_mapping_overpass(
                    region=region,
                    mapping=mapping,
                    api_endpoint=api_endpoint,
                    headers=headers,
                    queries_md=queries_md,
                    since=since,
                    limit=limit,
                    console=console,
                    server_start_index=server_start_index,
                )
            )
            # Show download stats immediately after fetch
            fetch_status = f"[dim]↓{element_count} ({download_size // 1024}KB)[/dim]"
            progress.update(
                task_id,
                completed=1,
                server=f"[dim][{server_label}][/dim]",
                status=fetch_status,
            )

            if elements is None:
                progress.update(
                    task_id,
                    completed=3,
                    mapping=f"{mapping.category_slug}",
                    status="[red]✗ FAILED[/red]",
                )
                progress.stop_task(task_id)
                progress.advance(overall_task)
                return {
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "deleted": 0,
                    "download_bytes": 0,
                    "server_label": server_label,
                    "mapping_slug": mapping.category_slug,
                    "success": False,
                }

            # PIPELINE STAGE 2: PROCESS
            processing_status = f"[cyan]processing...[/cyan] [dim]↓{element_count} ({download_size // 1024}KB)[/dim]"
            progress.update(
                task_id, status=processing_status, server=""
            )  # Clear server label
            amenities = self._process_elements(
                elements=elements,
                mapping=mapping,
                category_names=category_names,
            )
            progress.update(task_id, completed=2)

            # PIPELINE STAGE 3: IMPORT
            importing_status = f"[magenta]importing...[/magenta] [dim]↓{element_count} ({download_size // 1024}KB)[/dim]"
            progress.update(task_id, status=importing_status)
            created, updated, skipped, deleted, errors = self._import_amenities(
                amenities=amenities,
                osm_org=osm_org,
                run_start=run_start,
                dry_run=dry_run,
            )
            progress.update(task_id, completed=3)

            # Update final status (element_count already set from fetch)
            status_parts = []
            if created:
                status_parts.append(f"[green]+{created}[/green]")
            if updated:
                status_parts.append(f"[yellow]~{updated}[/yellow]")
            if deleted:
                status_parts.append(f"[red]-{deleted}[/red]")
            if errors:
                status_parts.append(f"[red]!{errors}[/red]")
            if skipped:
                status_parts.append(f"[dim]·{skipped}[/dim]")
            if download_size and element_count:
                status_parts.append(
                    f"[cyan]↓{element_count} ({download_size // 1024}KB)[/cyan]"
                )

            status = (
                "[green]✓[/green] " + " ".join(status_parts)
                if status_parts
                else "[green]✓[/green]"
            )
            progress.update(task_id, status=status, server="")  # Clear server label
            progress.stop_task(task_id)
            progress.advance(overall_task)

            return {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "deleted": deleted,
                "errors": errors,
                "download_bytes": download_size,
                "server_label": server_label,
                "mapping_slug": mapping.category_slug,
                "success": True,
            }

        except Exception as e:
            # Log exception to error list
            if not hasattr(self, "_import_errors"):
                self._import_errors = []

            self._import_errors.append(
                {
                    "name": f"Worker {worker_id}",
                    "category": mapping.category_slug,
                    "error": f"Worker exception: {str(e)}",
                }
            )

            progress.update(
                task_id,
                completed=3,
                mapping=f"{mapping.category_slug}",
                status=f"[red]✗ ERROR: {str(e)[:30]}[/red]",
                server="",
            )
            progress.stop_task(task_id)
            progress.advance(overall_task)
            return {
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "deleted": 0,
                "errors": 1,
                "download_bytes": 0,
                "server_label": "",
                "mapping_slug": "",
                "success": False,
            }
        finally:
            # Close database connection for this thread
            connection.close()

    def _process_overpass_parallel(
        self,
        region: str,
        category_names: list[str],
        osm_org: Organization,
        run_start: datetime,
        workers: int = 4,
        limit: int | None = None,
        overpass_server: str | None = None,
        overpass_queries_file: str | None = None,
        since: str | None = None,
        dry_run: bool = False,
        state: dict | None = None,
        state_file: Path | None = None,
    ):
        """Process Overpass mappings in parallel using ThreadPoolExecutor.

        Args:
            workers: Number of parallel workers
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        from rich.console import Console
        from rich.progress import (
            Progress,
            SpinnerColumn,
            BarColumn,
            TextColumn,
            TimeElapsedColumn,
        )
        from rich.panel import Panel

        console = Console()

        # Store region for use in _guess_country_code during place creation
        self._current_region = region.upper()

        # Parse since parameter
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                console.print(f"[red]Invalid --since format: {since}[/red]")
                return

        # Load queries
        queries_md = {}
        if overpass_queries_file:
            queries_md = self._load_queries_file(overpass_queries_file)

        # Determine API endpoint
        api_endpoint = None
        server_name = "Server Pool (A/B/C)"
        if overpass_server:
            api_endpoint = overpass_server
            server_name = overpass_server.split("/")[2]

        headers = {"User-Agent": "Wodore/1.0 (https://wodore.com) Python/httpx"}

        # Get categories and build mapping list
        categories = get_categories(category_names)
        all_mappings = []
        for cat in categories:
            for mapping in cat.mappings:
                all_mappings.append((cat.category, mapping))

        total_mappings = len(all_mappings)

        # Build server pool display
        if api_endpoint:
            server_display = f"Server: {server_name}"
        else:
            server_lines = "Server Pool:\n"
            for label, url in OVERPASS_SERVERS:
                server_lines += f"  [{label}] {url.split('/')[2]}\n"
            server_display = server_lines.rstrip()

        # Print header
        header_text = f"OSM Import Pipeline: [bold cyan]{region.upper()}[/bold cyan]\n"
        header_text += server_display + "\n"
        header_text += f"Workers: {workers} | Mappings: {total_mappings}"
        if since:
            header_text += f" | Incremental: since {since}"
        if dry_run:
            header_text += " | [yellow]DRY RUN[/yellow]"
        console.print(Panel(header_text, expand=False))

        # Print symbols footer
        console.print(
            "[dim]Symbols: ✓ = completed | ✗ = failed | +N = created | ~N = updated | -N = deleted | !N = errors | ·N = skipped | ↓N (KB) = downloaded[/dim]\n"
        )

        # Initialize counters
        total_created = 0
        total_updated = 0
        total_skipped = 0
        total_deleted = 0
        total_download_bytes = 0

        # Create progress display with auto-cleanup of completed tasks
        # Rich's get_renderable_tasks method limits visible tasks by default, so we override it

        class ShowAllProgress(Progress):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.completed_times = {}  # Track when tasks complete

            def stop_task(self, task_id):
                """Override to track completion time."""
                super().stop_task(task_id)
                self.completed_times[task_id] = time.time()

            def get_renderable_tasks(self):
                """Override to show all tasks without filtering, but auto-remove after 30s."""
                current_time = time.time()
                # Remove tasks that completed more than 30 seconds ago
                tasks_to_remove = [
                    task_id
                    for task_id, completion_time in self.completed_times.items()
                    if current_time - completion_time > 30
                ]
                for task_id in tasks_to_remove:
                    # Find and remove the task
                    self.tasks = [task for task in self.tasks if task.id != task_id]
                    del self.completed_times[task_id]

                # Deduplicate tasks by task_id to prevent duplicates in display
                seen_ids = set()
                unique_tasks = []
                for task in self.tasks:
                    if task.id not in seen_ids:
                        seen_ids.add(task.id)
                        unique_tasks.append(task)
                return unique_tasks

        with (
            ShowAllProgress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.fields[mapping]:<35}", justify="left"),
                BarColumn(bar_width=30, complete_style="cyan", finished_style="green"),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TextColumn("•"),
                TextColumn("{task.fields[status]}", markup=True),
                console=console,
                expand=False,
                refresh_per_second=2,  # Reduce refresh rate further to minimize rendering glitches
            ) as progress
        ):
            # Add overall progress task
            overall_task = progress.add_task(
                "Overall",
                total=total_mappings,
                mapping="[bold]Overall Progress[/bold]",
                status="",
            )

            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit tasks with staggered start
                futures = []
                num_servers = len(OVERPASS_SERVERS)

                for idx, mapping_data in enumerate(all_mappings):
                    # Staggered start logic:
                    # - First batch (0 to num_servers-1): start immediately
                    # - Second batch (num_servers to 2*num_servers-1): delay 2 seconds
                    # - Rest: no delay (will queue naturally)
                    if idx >= num_servers and idx < 2 * num_servers:
                        time.sleep(2)

                    future = executor.submit(
                        self._process_mapping_worker,
                        worker_id=idx,  # Use idx as worker_id for server rotation
                        mapping_data=mapping_data,
                        region=region,
                        osm_org=osm_org,
                        run_start=run_start,
                        category_names=category_names,
                        api_endpoint=api_endpoint,
                        headers=headers,
                        queries_md=queries_md,
                        since=since_dt,
                        limit=limit,
                        dry_run=dry_run,
                        console=console,
                        progress=progress,
                        overall_task=overall_task,
                    )
                    futures.append(future)

                # Collect results as they complete
                total_errors = 0
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        total_created += result["created"]
                        total_updated += result["updated"]
                        total_skipped += result["skipped"]
                        total_deleted += result.get("deleted", 0)
                        total_errors += result.get("errors", 0)
                        total_download_bytes += result["download_bytes"]

                        # Update state for this mapping
                        if state is not None and result.get("success"):
                            mapping_slug = result.get("mapping_slug")
                            if mapping_slug:
                                count = result["created"] + result["updated"]
                                self._update_mapping_state(
                                    state,
                                    region,
                                    mapping_slug,
                                    run_start.isoformat(),
                                    count,
                                )
                    except Exception as e:
                        console.log(f"[red]Worker exception: {e}[/red]")
                        total_errors += 1

        # Write errors to log file if any occurred
        if hasattr(self, "_import_errors") and self._import_errors:
            error_log_path = Path(
                f"osm_import_errors_{region}_{run_start.strftime('%Y%m%d_%H%M%S')}.log"
            )
            with open(error_log_path, "w") as f:
                f.write(f"OSM Import Errors - {region} - {run_start}\n")
                f.write("=" * 80 + "\n\n")
                for idx, error in enumerate(self._import_errors, 1):
                    f.write(f"{idx}. {error['name']}\n")
                    f.write(f"   Category: {error.get('category', 'N/A')}\n")
                    if error.get("osm_type") and error.get("osm_id"):
                        f.write(f"   OSM: {error['osm_type']}/{error['osm_id']}\n")
                    f.write(f"   Error: {error['error']}\n")
                    f.write("\n")
            console.print(f"[yellow]Errors logged to: {error_log_path}[/yellow]")

        # Set instance variables for handle method to use
        self._pipeline_created = total_created
        self._pipeline_updated = total_updated
        self._pipeline_skipped = total_skipped
        self._pipeline_deleted = total_deleted
        self._pipeline_errors = total_errors

    def _process_overpass_pipeline(
        self,
        region: str,
        category_names: list[str],
        osm_org: Organization,
        run_start: datetime,
        limit: int | None = None,
        overpass_server: str | None = None,
        overpass_queries_file: str | None = None,
        since: str | None = None,
        dry_run: bool = False,
        state: dict | None = None,
        state_file: Path | None = None,
    ) -> bool:
        """Process Overpass data using pipeline approach (fetch → process → import per mapping).

        Args:
            region: Country code (e.g., CH, AT, DE)
            category_names: List of category names to fetch
            osm_org: OSM Organization instance
            run_start: Import start timestamp
            limit: If set, limit amenities per mapping (for testing)
            overpass_server: Overpass API server URL (if None, use pool)
            overpass_queries_file: If set, write queries to markdown file
            since: If set, only fetch elements modified since this timestamp
            dry_run: If True, don't make DB changes

        Returns:
            True on success, False on error
        """
        import time
        from rich.console import Console
        from rich.progress import (
            Progress,
            SpinnerColumn,
            BarColumn,
            TextColumn,
            TimeElapsedColumn,
        )
        from rich.panel import Panel

        console = Console()

        # Store region for use in _guess_country_code during place creation
        self._current_region = region.upper()

        # Open queries file if specified
        queries_md = None
        if overpass_queries_file:
            queries_md = open(overpass_queries_file, "w")
            queries_md.write(f"# Overpass Queries for {region}\n\n")
            queries_md.write(
                f"Generated for categories: {', '.join(category_names)}\n\n"
            )

        # Determine API endpoint
        if overpass_server:
            api_endpoint = overpass_server
            server_name = overpass_server.split("/")[2]
        else:
            # Pool of Overpass API endpoints
            overpass_endpoints = [
                "https://overpass.private.coffee/api/interpreter",
                "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                "https://overpass-api.de/api/interpreter",
            ]
            api_endpoint = overpass_endpoints[0]
            server_name = api_endpoint.split("/")[2]

        headers = {"User-Agent": "Wodore/1.0 (https://wodore.com) Python/httpx"}

        # Initialize counters
        self._pipeline_created = 0
        self._pipeline_updated = 0
        self._pipeline_skipped = 0
        self._pipeline_deleted = 0
        total_download_bytes = 0

        # Get categories and build mapping list
        categories = get_categories(category_names)
        all_mappings = []
        for cat in categories:
            for mapping in cat.mappings:
                all_mappings.append((cat.category, mapping))

        total_mappings = len(all_mappings)

        # Print header
        header_text = f"OSM Import Pipeline: [bold cyan]{region.upper()}[/bold cyan]\n"
        header_text += f"Server: {server_name} | Mappings: {total_mappings}"
        if since:
            header_text += f" | Incremental: since {since}"
        if dry_run:
            header_text += " | [yellow]DRY RUN[/yellow]"
        console.print(Panel(header_text, expand=False))

        # Print symbols footer that stays visible
        console.print(
            "[dim]Symbols: ✓ = completed | ✗ = failed | +N = created | ~N = updated | -N = deleted | !N = errors | ·N = skipped | ↓N = downloaded[/dim]\n"
        )

        # Create progress bars
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.fields[mapping]:<35}", justify="left"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[status]}", markup=True),
            TextColumn("{task.fields[server]}"),
            console=console,
            expand=False,
        ) as progress:
            # Add overall progress task
            overall_task = progress.add_task(
                "Overall",
                total=total_mappings,
                mapping="[bold]Overall Progress[/bold]",
                status="",
                server="",
            )

            # Track completed tasks
            completed_tasks = []

            # Process each mapping
            for idx, (category_name, mapping) in enumerate(all_mappings):
                mapping_start = time.time()

                # Add new task for this mapping
                current_task = progress.add_task(
                    f"mapping_{idx}",
                    total=3,  # 3 stages: fetch, process, import
                    mapping=f"{mapping.category_slug}",
                    status="[yellow]fetching...[/yellow]",
                    server="",
                )

                # PIPELINE STAGE 1: FETCH
                elements, download_size, server_label, element_count = (
                    self._fetch_mapping_overpass(
                        region=region,
                        mapping=mapping,
                        api_endpoint=api_endpoint,
                        headers=headers,
                        queries_md=queries_md,
                        since=since,
                        limit=limit,
                        console=console,
                    )
                )
                progress.update(current_task, completed=1, server=server_label)

                if elements is None:
                    progress.update(
                        current_task,
                        completed=3,
                        mapping=f"{mapping.category_slug}",
                        status="[red]✗ FAILED[/red]",
                    )
                    progress.stop_task(current_task)
                    completed_tasks.append(current_task)
                    progress.advance(overall_task)
                    continue

                total_download_bytes += download_size

                # PIPELINE STAGE 2: PROCESS
                progress.update(current_task, status="[cyan]processing...[/cyan]")
                amenities = self._process_elements(
                    elements=elements,
                    mapping=mapping,
                    category_names=category_names,
                )
                progress.update(current_task, completed=2)

                # Pre-cache data for this mapping
                self._precache_mapping_data(amenities)

                # PIPELINE STAGE 3: IMPORT
                progress.update(current_task, status="[magenta]importing...[/magenta]")
                created, updated, skipped, deleted, errors = self._import_amenities(
                    amenities=amenities,
                    osm_org=osm_org,
                    run_start=run_start,
                    dry_run=dry_run,
                )
                progress.update(current_task, completed=3)

                self._pipeline_created += created
                self._pipeline_updated += updated
                self._pipeline_skipped += skipped
                self._pipeline_deleted = getattr(self, "_pipeline_deleted", 0) + deleted
                self._pipeline_errors = getattr(self, "_pipeline_errors", 0) + errors

                mapping_time = time.time() - mapping_start

                # Format download size
                if download_size < 1024:
                    size_str = f"{download_size}B"
                elif download_size < 1024 * 1024:
                    size_str = f"{download_size / 1024:.1f}KB"
                else:
                    size_str = f"{download_size / (1024 * 1024):.1f}MB"

                # Build changes display
                changes_parts = []
                if created:
                    changes_parts.append(f"[green]+{created}[/green]")
                if updated:
                    changes_parts.append(f"[yellow]~{updated}[/yellow]")
                if deleted:
                    changes_parts.append(f"[red]-{deleted}[/red]")
                if errors:
                    changes_parts.append(f"[red]!{errors}[/red]")
                if skipped:
                    changes_parts.append(f"·{skipped}")
                changes_str = " ".join(changes_parts) if changes_parts else "·0"

                # Show downloaded count with size (element_count is actual downloaded)
                downloaded_str = f"↓{element_count} ({size_str})"

                # Update with completion status and mark as done
                progress.update(
                    current_task,
                    completed=3,
                    mapping=f"{mapping.category_slug}",
                    status=f"[green]✓[/green] {changes_str} {downloaded_str} │ {mapping_time:.1f}s",
                )

                # Stop the spinner for completed task
                progress.stop_task(current_task)
                completed_tasks.append(current_task)

                progress.advance(overall_task)

                # Update state for this mapping
                if state is not None:
                    count = created + updated
                    self._update_mapping_state(
                        state,
                        region,
                        mapping.category_slug,
                        run_start.isoformat(),
                        count,
                    )

        # Close queries file
        if queries_md:
            queries_md.close()
            console.print(f"[dim]Queries written to: {overpass_queries_file}[/dim]")

        # Write errors to log file if any occurred
        error_count = getattr(self, "_pipeline_errors", 0)
        if hasattr(self, "_import_errors") and self._import_errors:
            error_log_path = Path(
                f"osm_import_errors_{region}_{run_start.strftime('%Y%m%d_%H%M%S')}.log"
            )
            with open(error_log_path, "w") as f:
                f.write(f"OSM Import Errors - {region} - {run_start}\n")
                f.write("=" * 80 + "\n\n")
                for idx, error in enumerate(self._import_errors, 1):
                    f.write(f"{idx}. {error['name']}\n")
                    f.write(f"   Category: {error.get('category', 'N/A')}\n")
                    if error.get("osm_type") and error.get("osm_id"):
                        f.write(f"   OSM: {error['osm_type']}/{error['osm_id']}\n")
                    f.write(f"   Error: {error['error']}\n")
                    f.write("\n")
            console.print(f"[yellow]Errors logged to: {error_log_path}[/yellow]")

        # Print summary
        total_time = time.time() - run_start.timestamp()
        total_download_mb = total_download_bytes / (1024 * 1024)

        if error_count > 0:
            console.print(
                "\n[bold yellow]⚠ Import completed with errors![/bold yellow]"
            )
        else:
            console.print("\n[bold green]✓ Import complete![/bold green]")

        summary_parts = [
            f"Created: [green]{self._pipeline_created}[/green]",
            f"Updated: [yellow]{self._pipeline_updated}[/yellow]",
        ]
        if self._pipeline_deleted:
            summary_parts.append(f"Deleted: [red]{self._pipeline_deleted}[/red]")
        if error_count > 0:
            summary_parts.append(f"Errors: [red]{error_count}[/red]")
        summary_parts.append(f"Skipped: {self._pipeline_skipped}")
        console.print("  " + " | ".join(summary_parts))
        console.print(
            f"  Downloaded: [cyan]{total_download_mb:.2f} MB[/cyan] | "
            f"Runtime: [cyan]{total_time:.1f}s[/cyan]"
        )

        return True

    def _process_full_json(self, json_data: dict) -> list[OSMElement]:
        """Convert JSON response to OSMElement list.

        All elements get action=None since we don't know if they changed.

        Args:
            json_data: Parsed JSON response from Overpass API

        Returns:
            List of OSMElement with action=None
        """
        elements = []
        for elem in json_data.get("elements", []):
            # Get coordinates
            if elem["type"] == "node":
                lat = elem.get("lat")
                lon = elem.get("lon")
            else:  # way or relation
                # Overpass returns center for ways when using 'out center'
                center = elem.get("center", {})
                lat = center.get("lat")
                lon = center.get("lon")

            if lat is None or lon is None:
                continue  # Skip if no coordinates

            elements.append(
                OSMElement(
                    osm_id=f"{elem['type']}/{elem['id']}",
                    osm_type=elem["type"],
                    lat=lat,
                    lon=lon,
                    tags=elem.get("tags", {}),
                    action=None,  # Full import - don't know if changed
                    version=elem.get("version", 0),
                    timestamp=elem.get("timestamp", ""),
                )
            )

        return elements

    def _process_diff_xml(self, xml_data: str) -> list[OSMElement]:
        """Convert XML diff response to OSMElement list.

        Parses <action type="create|modify|delete"> elements from Overpass diff.

        Args:
            xml_data: Raw XML string from Overpass API diff mode

        Returns:
            List of OSMElement with action='create', 'modify', or 'delete'
        """
        import xml.etree.ElementTree as ET

        elements = []
        root = ET.fromstring(xml_data)

        for action_elem in root.findall("action"):
            action_type = action_elem.get("type")  # create, modify, delete

            # Get the element (could be in <new> or <old> tag)
            elem_container = action_elem.find("new") or action_elem.find("old")
            if elem_container is None:
                continue

            osm_elem = elem_container.find("node") or elem_container.find("way")
            if osm_elem is None:
                continue

            # Extract tags
            tags = {}
            for tag in osm_elem.findall("tag"):
                tags[tag.get("k")] = tag.get("v")

            # Get coordinates
            if osm_elem.tag == "node":
                lat = float(osm_elem.get("lat"))
                lon = float(osm_elem.get("lon"))
            else:  # way
                # For ways, use center from <center> tag
                center = osm_elem.find("center")
                if center is not None:
                    lat = float(center.get("lat"))
                    lon = float(center.get("lon"))
                else:
                    continue  # Skip ways without center

            elements.append(
                OSMElement(
                    osm_id=f"{osm_elem.tag}/{osm_elem.get('id')}",
                    osm_type=osm_elem.tag,
                    lat=lat,
                    lon=lon,
                    tags=tags,
                    action=action_type,  # create, modify, delete
                    version=int(osm_elem.get("version", 0)),
                    timestamp=osm_elem.get("timestamp", ""),
                )
            )

        return elements

    def _fetch_mapping_overpass(
        self,
        region: str,
        mapping,
        api_endpoint: str,
        headers: dict,
        queries_md,
        since: str | None,
        limit: int | None,
        console=None,
        server_start_index: int = 0,
    ) -> tuple[list[OSMElement] | None, int, str, int]:
        """Fetch elements for a single mapping from Overpass API.

        Args:
            server_start_index: Index to start server rotation (for load balancing)

        Returns:
            Tuple of (list of OSMElement or None on error, download size in bytes, server label used, element count)
        """
        import httpx
        import time
        import json

        # If custom server provided, use it directly
        if api_endpoint:
            server_label = "custom"
            servers_to_try = [(server_label, api_endpoint)]
        else:
            # Try all servers starting from server_start_index
            servers_to_try = []
            for offset in range(len(OVERPASS_SERVERS)):
                idx = (server_start_index + offset) % len(OVERPASS_SERVERS)
                servers_to_try.append(OVERPASS_SERVERS[idx])

        # Build Overpass query from osm_filters
        filters_parts = []

        # Build newer filter if needed (only for non-diff mode)
        # For diff mode, the diff directive handles time filtering
        newer_filter = f'(newer:"{since}")' if since else ""
        use_diff_mode = bool(since)  # Use diff mode when since is provided

        for filter_item in mapping.osm_filters:
            if isinstance(filter_item, tuple):
                # OR: create union of separate queries
                for tag in filter_item:
                    if "=" in tag:
                        key, value = tag.split("=", 1)
                        filters_parts.append(
                            f'node{newer_filter}["{key}"="{value}"](area.a);'
                        )
                        filters_parts.append(
                            f'way{newer_filter}["{key}"="{value}"](area.a);'
                        )
                    else:
                        filters_parts.append(f'node{newer_filter}["{tag}"](area.a);')
                        filters_parts.append(f'way{newer_filter}["{tag}"](area.a);')
            elif isinstance(filter_item, str):
                # AND: add to filter chain
                if "=" in filter_item:
                    key, value = filter_item.split("=", 1)
                    filters_parts.append(
                        f'node{newer_filter}["{key}"="{value}"](area.a);'
                    )
                    filters_parts.append(
                        f'way{newer_filter}["{key}"="{value}"](area.a);'
                    )
                else:
                    filters_parts.append(
                        f'node{newer_filter}["{filter_item}"](area.a);'
                    )
                    filters_parts.append(f'way{newer_filter}["{filter_item}"](area.a);')

        if not filters_parts:
            return [], 0, "", 0

        # Build Overpass QL query
        query = f"""
        area["ISO3166-1"="{region.upper()}"]->.a;
        (
            {chr(10).join("    " + fp for fp in filters_parts)}
        );
        out center;
        """

        # Write query to file if specified
        if queries_md:
            output_format = "xml" if use_diff_mode else "json"
            diff_directive = f'[diff:"{since}"]' if use_diff_mode else ""
            queries_md.write(f"## {mapping.category_slug}\n\n")
            queries_md.write(
                f"```\n[out:{output_format}]{diff_directive};\n{query.strip()}\n```\n\n"
            )
            queries_md.flush()

        # Try each server in rotation with retry logic
        max_retries_per_server = 2
        retry_delay = 5

        for server_label, server_url in servers_to_try:
            for attempt in range(max_retries_per_server):
                try:
                    # Build query with appropriate output format
                    if use_diff_mode:
                        # XML diff mode for incremental updates
                        full_query = f'[out:xml][diff:"{since}"][timeout:300];{query}'
                    else:
                        # JSON mode for full imports
                        full_query = f"[out:json][timeout:300];{query}"

                    response = httpx.post(
                        server_url,
                        data={"data": full_query},
                        headers=headers,
                        timeout=300.0,
                    )
                    response.raise_for_status()

                    # Get raw response text before parsing
                    response_text = response.text

                    # Calculate download size from uncompressed response text
                    download_size = len(response_text.encode("utf-8"))

                    # Parse response based on mode
                    if use_diff_mode:
                        # Parse XML diff response
                        all_elements = self._process_diff_xml(response_text)
                    else:
                        # Parse JSON response
                        result = response.json()
                        all_elements = self._process_full_json(result)

                    element_count = len(all_elements)

                    # Apply limit if specified
                    if limit:
                        return (
                            all_elements[:limit],
                            download_size,
                            server_label,
                            element_count,
                        )
                    return all_elements, download_size, server_label, element_count

                except Exception as e:
                    # Check if it's a retryable error
                    is_rate_limit = isinstance(
                        e, httpx.HTTPStatusError
                    ) and e.response.status_code in [429, 503, 504]
                    is_json_error = isinstance(e, json.JSONDecodeError)

                    if (
                        is_rate_limit or is_json_error
                    ) and attempt < max_retries_per_server - 1:
                        wait_time = retry_delay * (2**attempt)  # Exponential backoff
                        # Sleep and retry silently - status is shown in progress bar
                        time.sleep(wait_time)
                        continue

                    # This attempt failed, break to try next server
                    break

        # All servers failed - log error
        if console:
            error_msg = f"[red]All servers failed for {mapping.category_slug}[/red]"
            console.log(error_msg)

        return None, 0, "", 0

    def _process_elements(
        self,
        elements: list[OSMElement],
        mapping,
        category_names: list[str],
    ) -> list[dict]:
        """Process OSMElement list into amenity data format.

        Returns:
            List of amenity dicts with 'action' field from OSMElement
        """
        from server.apps.geometries.config.osm_categories import match_tags_to_category

        amenities = []

        for element in elements:
            # Pre-process tags if hook exists
            tags = element.tags.copy()
            if mapping.pre_process:
                tags = mapping.pre_process(tags)

            # Check if tags match (for AND logic with multiple filter items)
            match_result = match_tags_to_category(tags, category_names)
            if not match_result:
                continue

            category_slug, _, _ = match_result

            # OSMElement already has lat/lon extracted
            lat = element.lat
            lon = element.lon

            # Extract osm_id from "node/123" or "way/456" format
            osm_type = element.osm_type
            osm_id_str = element.osm_id.split("/")[-1]  # Get numeric part
            osm_id = int(osm_id_str)

            # Extract amenity data
            data = {
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
                "action": element.action,  # Include action for diff mode handling
            }

            # Post-process data if hook exists
            if mapping.post_process:
                data = mapping.post_process(tags, data)

            amenities.append(data)

        return amenities

    def _precache_mapping_data(self, amenities: list[dict]):
        """Pre-cache categories and brands for a mapping's amenities."""
        if not amenities:
            return

        # Collect unique category slugs and brands
        category_slugs = set()
        brands = set()

        for data in amenities:
            category_slugs.add(data["category_slug"])
            if data.get("brand"):
                brands.add(data["brand"].lower())

        # Pre-create categories if not cached
        if not hasattr(self, "_category_cache"):
            self._category_cache = {}

        for category_slug in category_slugs:
            if category_slug not in self._category_cache:
                try:
                    self._category_cache[category_slug] = self._get_or_create_category(
                        category_slug
                    )
                except Exception:
                    pass

        # Pre-create brand categories if not cached
        if not hasattr(self, "_brand_cache"):
            self._brand_cache = {}

        if brands:
            brand_parent, _ = Category.objects.get_or_create(
                slug="brand",
                defaults={"name": "Brand"},
            )

            for brand_name in brands:
                if brand_name not in self._brand_cache:
                    brand_slug = brand_name.replace(" ", "_")[:50]
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

    def _import_amenities(
        self,
        amenities: list[dict],
        osm_org: Organization,
        run_start: datetime,
        dry_run: bool,
    ) -> tuple[int, int, int, int, int]:
        """Import amenities to database.

        Returns:
            Tuple of (created_count, updated_count, skipped_count, deleted_count, error_count)
        """
        created_count = 0
        updated_count = 0
        skipped_count = 0
        deleted_count = 0
        error_count = 0

        for data in amenities:
            action = data.get("action")  # None, "create", "modify", "delete"

            if dry_run:
                action_str = f"[{action}] " if action else ""
                self.stdout.write(
                    f"    [DRY RUN] {action_str}Would upsert: {data['name'] or 'Unnamed'} "
                    f"({data['category_slug']}) at ({data['lat']}, {data['lon']})"
                )
                continue

            try:
                # Handle deletions separately
                if action == "delete":
                    osm_id_str = f"{data['osm_type']}/{data['osm_id']}"
                    deleted = self._deactivate_by_osm_id(osm_id_str, osm_org)
                    if deleted:
                        deleted_count += 1
                    else:
                        skipped_count += 1  # Already deleted or doesn't exist
                else:
                    # Create or modify
                    result = self._upsert_amenity(data, osm_org, run_start)
                    if result == "created":
                        created_count += 1
                    elif result == "updated":
                        updated_count += 1
                    else:
                        skipped_count += 1
            except Exception as e:
                error_count += 1
                # Log error to instance variable for later reporting
                if not hasattr(self, "_import_errors"):
                    self._import_errors = []

                error_info = {
                    "name": data.get("name", "Unnamed"),
                    "osm_type": data.get("osm_type"),
                    "osm_id": data.get("osm_id"),
                    "category": data.get("category_slug"),
                    "error": str(e),
                }
                self._import_errors.append(error_info)

        return created_count, updated_count, skipped_count, deleted_count, error_count

    def _fetch_overpass(
        self,
        country_code: str,
        category_names: list[str],
        limit: int | None = None,
        queries_file: str | None = None,
        since: str | None = None,
    ) -> list[dict] | None:
        """Fetch amenities from Overpass API.

        Args:
            country_code: ISO3166-1 country code (e.g., CH, AT, DE)
            category_names: List of category names to fetch
            limit: If set, only process up to LIMIT amenities per mapping (for testing)
            queries_file: If set, write all queries to this markdown file (for debugging)
            since: If set, only fetch elements modified since this timestamp (ISO format)

        Returns:
            List of amenity dicts in same format as PBF parser, or None on error
        """
        import httpx

        # Open queries file if specified
        queries_md = None
        if queries_file:
            queries_md = open(queries_file, "w")
            queries_md.write(f"# Overpass Queries for {country_code}\n\n")
            queries_md.write(
                f"Generated for categories: {', '.join(category_names)}\n\n"
            )

        # Pool of Overpass API endpoints with fallback
        overpass_endpoints = [
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass-api.de/api/interpreter",
        ]

        # Use first endpoint (will rotate on errors via retry logic)
        api_endpoint = overpass_endpoints[0]
        self.stdout.write(f"Using Overpass endpoint: {api_endpoint}")

        headers = {"User-Agent": "Wodore/1.0 (https://wodore.com) Python/httpx"}

        amenities = []

        categories = get_categories(category_names)

        for cat in categories:
            self.stdout.write(f"  Fetching category: {cat.category}")

            for mapping in cat.mappings:
                self.stdout.write(f"    Mapping: {mapping.category_slug}")
                self.stdout.write("      [1/3] Fetching from Overpass API...")

                # Build Overpass query from osm_filters
                filters_parts = []

                for filter_item in mapping.osm_filters:
                    if isinstance(filter_item, tuple):
                        # OR: create union of separate queries
                        for tag in filter_item:
                            if "=" in tag:
                                key, value = tag.split("=", 1)
                                filters_parts.append(
                                    f'node["{key}"="{value}"](area.a);'
                                )
                                filters_parts.append(f'way["{key}"="{value}"](area.a);')
                            else:
                                filters_parts.append(f'node["{tag}"](area.a);')
                                filters_parts.append(f'way["{tag}"](area.a);')
                    elif isinstance(filter_item, str):
                        # AND: add to filter chain
                        if "=" in filter_item:
                            key, value = filter_item.split("=", 1)
                            filters_parts.append(f'node["{key}"="{value}"](area.a);')
                            filters_parts.append(f'way["{key}"="{value}"](area.a);')
                        else:
                            filters_parts.append(f'node["{filter_item}"](area.a);')
                            filters_parts.append(f'way["{filter_item}"](area.a);')

                if not filters_parts:
                    continue

                # Build Overpass QL query (library adds [out:json] automatically)
                # Add (newer:"timestamp") filter for incremental updates if since is provided
                newer_filter = f'(newer:"{since}")' if since else ""
                query = f"""
                area["ISO3166-1"="{country_code.upper()}"]->.a;
                (
                    {chr(10).join("    " + fp for fp in filters_parts)}
                ){newer_filter};
                out center;
                """

                # Write query to file if specified
                if queries_md:
                    queries_md.write(f"## {cat.category} - {mapping.category_slug}\n\n")
                    queries_md.write(f"```\n[out:json];\n{query.strip()}\n```\n\n")
                    queries_md.flush()

                # Retry logic for rate limiting
                max_retries = 3
                retry_delay = 5  # seconds

                for attempt in range(max_retries):
                    try:
                        # Make direct HTTP request to Overpass API
                        # Add [out:json] header to query
                        full_query = f"[out:json][timeout:300];{query}"

                        response = httpx.post(
                            api_endpoint,
                            data={"data": full_query},
                            headers=headers,
                            timeout=300.0,
                        )
                        response.raise_for_status()
                        result = response.json()

                        self.stdout.write(
                            f"      Debug: API result type: {type(result)}"
                        )
                        self.stdout.write(
                            f"      Debug: API result keys: {result.keys() if isinstance(result, dict) else 'not a dict'}"
                        )
                        if isinstance(result, dict) and "elements" in result:
                            self.stdout.write(
                                f"      Debug: elements count in result: {len(result['elements'])}"
                            )
                        break  # Success, exit retry loop
                    except Exception as e:
                        import time
                        import json

                        # Check if it's a retryable error
                        is_rate_limit = isinstance(
                            e, httpx.HTTPStatusError
                        ) and e.response.status_code in [429, 503, 504]
                        is_json_error = isinstance(e, json.JSONDecodeError)

                        if (
                            is_rate_limit or is_json_error
                        ) and attempt < max_retries - 1:
                            wait_time = retry_delay * (
                                2**attempt
                            )  # Exponential backoff
                            error_type = (
                                "Rate limited"
                                if is_rate_limit
                                else "Invalid JSON response"
                            )
                            self.stdout.write(
                                self.style.WARNING(
                                    f"{error_type}. Waiting {wait_time}s before retry {attempt + 2}/{max_retries}..."
                                )
                            )
                            time.sleep(wait_time)
                            continue
                        # Re-raise if not retryable or max retries exceeded
                        raise

                try:
                    # Convert Overpass result to our format
                    all_elements = result.get("elements", [])

                    # Debug: show raw result
                    self.stdout.write(
                        f"      Debug: Overpass returned {len(all_elements)} elements"
                    )
                    if all_elements and len(all_elements) > 0:
                        self.stdout.write(
                            f"      Debug: First element: {all_elements[0]}"
                        )

                    # Apply limit per mapping if specified (for testing)
                    if limit:
                        elements = all_elements[:limit]
                        self.stdout.write(
                            f"      [2/3] Processing {len(elements)} elements (limited from {len(all_elements)})..."
                        )
                    else:
                        elements = all_elements
                        self.stdout.write(
                            f"      [2/3] Processing {len(elements)} elements..."
                        )

                    for element in elements:
                        # Pre-process tags if hook exists
                        tags = element.get("tags", {})
                        if mapping.pre_process:
                            tags = mapping.pre_process(tags)

                        # Check if tags match (for AND logic with multiple filter items)
                        from server.apps.geometries.config.osm_categories import (
                            match_tags_to_category,
                        )

                        match_result = match_tags_to_category(tags, category_names)
                        if not match_result:
                            continue

                        category_slug, _, _ = match_result

                        # Get location (Overpass returns 'center' for ways with 'out center')
                        if element["type"] == "node":
                            lat = element["lat"]
                            lon = element["lon"]
                        elif element["type"] == "way":
                            # Use center provided by Overpass
                            center = element.get("center")
                            if not center:
                                continue
                            lat = center["lat"]
                            lon = center["lon"]
                        else:
                            continue

                        # Extract amenity data
                        data = {
                            "osm_type": element["type"],
                            "osm_id": element["id"],
                            "lat": lat,
                            "lon": lon,
                            "tags": tags,
                            "category_slug": category_slug,
                            "mapcomplete_theme": mapping.mapcomplete_theme,
                            "name": tags.get("name", ""),
                            "opening_hours": tags.get("opening_hours"),
                            "phone": tags.get("phone") or tags.get("contact:phone"),
                            "website": tags.get("website")
                            or tags.get("contact:website"),
                            "brand": tags.get("brand"),
                        }

                        # Post-process data if hook exists
                        if mapping.post_process:
                            data = mapping.post_process(tags, data)

                        amenities.append(data)

                    self.stdout.write(
                        f"      [3/3] Collected {len(amenities)} amenities total"
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Overpass query failed for {cat.category}.{mapping.category_slug}: {e}"
                        )
                    )
                    self.stdout.write(
                        self.style.ERROR(f"Exception type: {type(e).__name__}")
                    )
                    self.stdout.write(self.style.ERROR(f"Query: {query}"))
                    import traceback

                    self.stdout.write(self.style.ERROR(traceback.format_exc()))
                    if queries_md:
                        queries_md.close()
                    return None

        # Close queries file
        if queries_md:
            queries_md.close()
            self.stdout.write(f"Queries written to: {queries_file}")

        return amenities

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
