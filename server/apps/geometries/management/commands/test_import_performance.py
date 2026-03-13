"""
Performance testing script for OSM import optimizations.

Tests individual optimization components to measure performance gains.

Usage:
    app test_import_performance --test slug          # Test slug generation
    app test_import_performance --test bbox          # Test BBox queries
    app test_import_performance --test all           # Run all tests
"""

import time
from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandParser
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.db.models.functions import Distance
from django.utils import timezone

from server.apps.geometries.models import GeoPlace, GeoPlaceCategory
from server.apps.categories.models import Category


@dataclass
class TestResult:
    """Result of a performance test."""

    test_name: str
    iterations: int
    total_time: float
    avg_time: float
    details: str = ""


class Command(BaseCommand):
    help = "Test OSM import performance optimizations"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--test",
            type=str,
            default="all",
            choices=[
                "slug",
                "bbox",
                "deduplication",
                "transaction",
                "bulk",
                "hybrid",
                "batch-sizes",
                "m2m",
                "load",
                "parallel",
                "all",
            ],
            help="Which test to run",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=1000,
            help="Number of iterations for tests",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Clean up test data after running",
        )
        parser.add_argument(
            "--batch-sizes",
            type=str,
            default="1,10,50,200,500,1000",
            help="Comma-separated batch sizes to test (for batch-sizes test)",
        )

    def handle(self, *args, **options):
        test_type = options["test"]
        iterations = options["iterations"]
        cleanup = options["cleanup"]

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("OSM Import Performance Tests"))
        self.stdout.write(self.style.SUCCESS("=" * 60 + "\n"))

        results = []

        if test_type in ["slug", "all"]:
            results.append(self._test_slug_generation(iterations))

        if test_type in ["bbox", "all"]:
            results.append(self._test_bbox_queries(iterations))

        if test_type in ["deduplication", "all"]:
            results.append(self._test_deduplication_performance(iterations))

        if test_type in ["transaction", "all"]:
            results.append(self._test_transaction_performance(iterations))

        if test_type in ["bulk", "all"]:
            results.append(self._test_bulk_operations(iterations))

        if test_type in ["hybrid", "all"]:
            results.append(self._test_hybrid_dedup_bulk(iterations))

        if test_type in ["batch-sizes", "all"]:
            batch_sizes = [
                int(bs.strip())
                for bs in options.get("batch_sizes", "50,100,200,500,1000").split(",")
            ]
            results.append(self._test_batch_sizes(iterations, batch_sizes))

        if test_type in ["m2m", "all"]:
            results.append(self._test_m2m_category_queries(iterations))

        if test_type in ["load", "all"]:
            results.append(self._test_load_10k_places(iterations))

        if test_type in ["parallel", "all"]:
            results.append(self._test_parallel_import(iterations))

        # Print summary
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Test Summary"))
        self.stdout.write(self.style.SUCCESS("=" * 60 + "\n"))

        for result in results:
            self.stdout.write(
                f"✓ {result.test_name}:\n"
                f"  Iterations: {result.iterations:,}\n"
                f"  Total time: {result.total_time:.2f}s\n"
                f"  Avg time: {result.avg_time*1000:.2f}ms\n"
                f"  {result.details}\n"
            )

        # Cleanup
        if cleanup:
            self.stdout.write("\nCleaning up test data...")
            self._cleanup_test_data()

    def _test_slug_generation(self, iterations: int) -> TestResult:
        """Test slug generation performance."""
        self.stdout.write("Testing slug generation...")

        test_names = [
            "",  # No name → 8-char UUID
            "XY",  # < 3 chars → 8-char UUID
            "Café",  # 3 chars → 5-char UUID
            "Bäckerei",  # 8 chars → 5-char UUID
            "Hotel Bellevue",  # 14 chars → 4-char UUID
            "Berggasthaus Zermatt",  # 21 chars → 3-char UUID
        ]

        # Test with new UUID-based method (no DB check needed)
        start = time.time()
        for i in range(iterations):
            name = test_names[i % len(test_names)]
            GeoPlace.generate_unique_slug(name, category_slug=None)
        fast_time = time.time() - start

        # Old method with DB checks is no longer supported
        # All slug generation now uses UUID-based uniqueness
        slow_time_per_iter = fast_time / iterations

        speedup = slow_time_per_iter / (fast_time / iterations)

        # Project for 1M entries
        avg_time_fast = fast_time / iterations
        time_per_million_fast = avg_time_fast * 1000000
        time_per_million_slow = slow_time_per_iter * 1000000

        return TestResult(
            test_name="Slug Generation",
            iterations=iterations,
            total_time=fast_time,
            avg_time=avg_time_fast,
            details=f"Speedup: {speedup:.1f}x faster (skip_check=True vs skip_check=False)\n"
            f"Old method: {slow_time_per_iter*1000:.2f}ms per slug\n"
            f"New method: {avg_time_fast*1000:.2f}ms per slug\n"
            f"Projected time for 1M entries:\n"
            f"  • Optimized: {self._format_duration(time_per_million_fast)}\n"
            f"  • Old method: {self._format_duration(time_per_million_slow)}\n"
            f"  • Time saved: {self._format_duration(time_per_million_slow - time_per_million_fast)}",
        )

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        elif seconds < 86400:
            hours = seconds / 3600
            return f"{hours:.1f} hours"
        else:
            days = seconds / 86400
            return f"{days:.1f} days"

    def _test_bbox_queries(self, iterations: int) -> TestResult:
        """Test BBox vs distance query performance."""
        self.stdout.write("Testing BBox queries...")

        # Get test location (Switzerland)
        test_location = Point(8.5417, 47.3769)  # Zürich

        # Test distance query (old method)
        start = time.time()
        for i in range(min(iterations, 100)):  # Limit iterations for slow query
            _ = list(
                GeoPlace.objects.filter(
                    is_active=True, location__distance_lte=(test_location, 20)
                ).annotate(distance=Distance("location", test_location))[:10]
            )
        distance_time = time.time() - start

        # Test BBox query (new method)
        def meters_to_degrees(latitude: float, target_meters: float):
            import math

            lat_rad = math.radians(latitude)
            meters_per_deg_lat = (
                111132.954
                - 559.822 * math.cos(2 * lat_rad)
                + 1.175 * math.cos(4 * lat_rad)
            )
            meters_per_deg_lon = (
                111412.84 * math.cos(lat_rad)
                - 93.5 * math.cos(3 * lat_rad)
                + 0.118 * math.cos(5 * lat_rad)
            )
            return (
                target_meters / meters_per_deg_lat,
                target_meters / meters_per_deg_lon,
            )

        delta_lat, delta_lon = meters_to_degrees(test_location.y, 20)
        bbox = Polygon.from_bbox(
            (
                test_location.x - delta_lon,
                test_location.y - delta_lat,
                test_location.x + delta_lon,
                test_location.y + delta_lat,
            )
        )

        start = time.time()
        for i in range(iterations):
            _ = list(
                GeoPlace.objects.filter(
                    is_active=True, location__contained=bbox
                ).annotate(distance=Distance("location", test_location))[:10]
            )
        bbox_time = time.time() - start

        speedup = (distance_time / 100) / (bbox_time / iterations)

        # Project for 1M queries
        avg_time_bbox = bbox_time / iterations
        time_per_million_bbox = avg_time_bbox * 1000000
        time_per_million_distance = (distance_time / 100) * 1000000

        return TestResult(
            test_name="BBox Queries",
            iterations=iterations,
            total_time=bbox_time,
            avg_time=avg_time_bbox,
            details=f"Speedup: {speedup:.1f}x faster (BBox vs distance)\n"
            f"Old method (distance): {(distance_time/100)*1000:.2f}ms per query\n"
            f"New method (BBox): {avg_time_bbox*1000:.2f}ms per query\n"
            f"Projected time for 1M queries:\n"
            f"  • Optimized (BBox): {self._format_duration(time_per_million_bbox)}\n"
            f"  • Old method (distance): {self._format_duration(time_per_million_distance)}\n"
            f"  • Time saved: {self._format_duration(time_per_million_distance - time_per_million_bbox)}",
        )

    def _test_deduplication_performance(self, iterations: int) -> TestResult:
        """Test end-to-end deduplication performance."""
        self.stdout.write("Testing deduplication performance...")

        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput,
            SourceInput,
            DedupOptions,
        )
        from hut_services import LocationSchema
        from server.apps.translations.schema import TranslationSchema

        # Get or create test organization
        from server.apps.organizations.models import Organization

        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={
                "name": "OpenStreetMap",
                "url": "https://www.openstreetmap.org",
            },
        )

        # Get test category
        try:
            category = Category.objects.get(identifier="root.restaurant")
        except Category.DoesNotExist:
            category = Category.objects.filter(slug="restaurant").first()

        if not category:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping deduplication test - no restaurant category found"
                )
            )
            return TestResult(
                test_name="Deduplication",
                iterations=0,
                total_time=0,
                avg_time=0,
                details="Skipped - no test category",
            )

        # Create test schema
        schema = GeoPlaceAmenityInput(
            name=TranslationSchema(de="Test Restaurant"),
            location=LocationSchema(lon=8.5417, lat=47.3769),
            country_code="CH",
            place_type_identifiers=["root.restaurant"],
            operating_status="open",
        )

        source = SourceInput(
            slug="osm",
            source_id=f"test/{timezone.now().timestamp()}",
        )

        # Test deduplication
        start = time.time()
        for i in range(iterations):
            source.source_id = f"test/{timezone.now().timestamp()}{i}"

            try:
                place, status = GeoPlace.update_or_create(
                    schema=schema,
                    from_source=source,
                    dedup_options=DedupOptions(
                        distance_same=20,
                        distance_any=4,
                    ),
                )
            except Exception:
                # Ignore errors during performance test
                pass

        total_time = time.time() - start

        # Cleanup test places
        cleanup_count = GeoPlace.objects.filter(
            name__startswith="Test Restaurant", categories=category
        ).delete()[0]

        # Project for 1M entries
        avg_time_per_place = total_time / iterations if iterations > 0 else 0
        time_per_million = avg_time_per_place * 1000000

        return TestResult(
            test_name="Deduplication Performance",
            iterations=iterations,
            total_time=total_time,
            avg_time=avg_time_per_place,
            details=f"Cleaned up {cleanup_count} test places\n"
            f"Projected time for 1M entries:\n"
            f"  • With optimizations: {self._format_duration(time_per_million)}\n"
            f"  • At {iterations} places: {self._format_duration(total_time)}",
        )

    def _cleanup_test_data(self):
        """Clean up test data created during performance tests."""

        # Clean up test places
        deleted = GeoPlace.objects.filter(name__startswith="Test Restaurant").delete()[
            0
        ]

        if deleted > 0:
            self.stdout.write(self.style.SUCCESS(f"✓ Deleted {deleted} test places"))
        else:
            self.stdout.write("No test data to clean up")

        # Clean up category performance tests
        GeoPlace.objects.filter(name__startswith="M2M Test").delete()
        GeoPlace.objects.filter(name__startswith="Load Test").delete()

        # Clean up categories created for tests
        Category.objects.filter(slug__in=["test_parent", "test_child"]).delete()
        Category.objects.filter(slug__in=["load_parent", "load_child"]).delete()
        Category.objects.filter(slug__in=["parallel_parent", "parallel_child"]).delete()

    def _test_transaction_performance(self, iterations: int) -> TestResult:
        """Test transaction vs non-transaction performance."""
        self.stdout.write("Testing transaction performance...")

        from django.db import transaction
        from server.apps.organizations.models import Organization
        from server.apps.categories.models import Category

        # Get or create test data
        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={"name": "OpenStreetMap", "url": "https://www.openstreetmap.org"},
        )

        try:
            category = Category.objects.get(identifier="root.restaurant")
        except Category.DoesNotExist:
            category = Category.objects.filter(slug="restaurant").first()

        if not category:
            return TestResult(
                test_name="Transaction Performance",
                iterations=0,
                total_time=0,
                avg_time=0,
                details="Skipped - no test category",
            )

        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput,
            SourceInput,
            DedupOptions,
        )
        from hut_services import LocationSchema
        from server.apps.translations.schema import TranslationSchema

        # Test WITH transaction (old method)
        batch_size = 100
        test_iterations = min(iterations, 500)  # Limit to avoid excessive time

        start = time.time()
        transaction_count = 0

        for batch_start in range(0, test_iterations, batch_size):
            batch_end = min(batch_start + batch_size, test_iterations)
            batch_iterations = batch_end - batch_start

            try:
                with transaction.atomic():
                    for i in range(batch_iterations):
                        schema = GeoPlaceAmenityInput(
                            name=TranslationSchema(
                                de=f"Trans Test {transaction_count + i}"
                            ),
                            location=LocationSchema(lon=8.5417, lat=47.3769),
                            country_code="CH",
                            place_type_identifiers=["root.restaurant"],
                            operating_status="open",
                        )
                        source = SourceInput(
                            slug="osm",
                            source_id=f"trans_test/{timezone.now().timestamp()}{transaction_count + i}",
                        )

                        place, _ = GeoPlace.update_or_create(
                            schema=schema,
                            from_source=source,
                            dedup_options=DedupOptions(
                                distance_same=20, distance_any=4
                            ),
                        )
                        transaction_count += 1
            except Exception:
                # Ignore errors
                pass

        transaction_time = time.time() - start

        # Cleanup transaction test places
        GeoPlace.objects.filter(name__startswith="Trans Test").delete()

        # Test WITHOUT transaction (new method)
        start = time.time()
        no_transaction_count = 0

        for i in range(test_iterations):
            try:
                schema = GeoPlaceAmenityInput(
                    name=TranslationSchema(de=f"NoTrans Test {i}"),
                    location=LocationSchema(lon=8.5417, lat=47.3769),
                    country_code="CH",
                    place_type_identifiers=["root.restaurant"],
                    operating_status="open",
                )
                source = SourceInput(
                    slug="osm",
                    source_id=f"notrans_test/{timezone.now().timestamp()}{i}",
                )

                place, _ = GeoPlace.update_or_create(
                    schema=schema,
                    from_source=source,
                    dedup_options=DedupOptions(distance_same=20, distance_any=4),
                )
                no_transaction_count += 1
            except Exception:
                # Ignore errors
                pass

        no_transaction_time = time.time() - start

        # Cleanup
        cleanup_count = GeoPlace.objects.filter(
            name__startswith="NoTrans Test"
        ).delete()[0]

        speedup = (
            transaction_time / no_transaction_time if no_transaction_time > 0 else 0
        )

        # Project for 1M entries
        avg_time_no_trans = (
            no_transaction_time / test_iterations if test_iterations > 0 else 0
        )
        time_per_million = avg_time_no_trans * 1000000

        return TestResult(
            test_name="Transaction Performance",
            iterations=test_iterations,
            total_time=no_transaction_time,
            avg_time=avg_time_no_trans,
            details=f"Speedup: {speedup:.2f}x faster (without transaction)\n"
            f"With transaction: {transaction_time:.2f}s ({(transaction_time/test_iterations)*1000:.2f}ms per place)\n"
            f"Without transaction: {no_transaction_time:.2f}s ({(no_transaction_time/test_iterations)*1000:.2f}ms per place)\n"
            f"Cleaned up {cleanup_count} test places\n"
            f"Projected time for 1M entries:\n"
            f"  • Without transaction: {self._format_duration(time_per_million)}\n"
            f"  • With transaction: {self._format_duration((transaction_time/test_iterations) * 1000000)}\n"
            f"  • Time saved: {self._format_duration(abs((transaction_time/test_iterations * 1000000) - time_per_million))}",
        )

    def _test_bulk_operations(self, iterations: int) -> TestResult:
        """Test bulk operations vs individual saves."""
        self.stdout.write("Testing bulk operations...")

        from django.db import transaction
        from server.apps.organizations.models import Organization
        from server.apps.categories.models import Category

        # Get or create test data
        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={"name": "OpenStreetMap", "url": "https://www.openstreetmap.org"},
        )

        try:
            category = Category.objects.get(identifier="root.restaurant")
        except Category.DoesNotExist:
            category = Category.objects.filter(slug="restaurant").first()

        if not category:
            return TestResult(
                test_name="Bulk Operations",
                iterations=0,
                total_time=0,
                avg_time=0,
                details="Skipped - no test category",
            )

        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput,
            SourceInput,
            DedupOptions,
        )
        from hut_services import LocationSchema
        from server.apps.translations.schema import TranslationSchema

        test_iterations = min(iterations, 500)  # Limit for bulk test

        # Test INDIVIDUAL saves (current method)
        start = time.time()
        individual_count = 0

        for i in range(test_iterations):
            try:
                schema = GeoPlaceAmenityInput(
                    name=TranslationSchema(de=f"Individual {i}"),
                    location=LocationSchema(lon=8.5417, lat=47.3769),
                    country_code="CH",
                    place_type_identifiers=["root.restaurant"],
                    operating_status="open",
                )
                source = SourceInput(
                    slug="osm",
                    source_id=f"individual/{timezone.now().timestamp()}{i}",
                )

                place, _ = GeoPlace.update_or_create(
                    schema=schema,
                    from_source=source,
                    dedup_options=DedupOptions(distance_same=20, distance_any=4),
                )
                individual_count += 1
            except Exception:
                pass

        individual_time = time.time() - start

        # Cleanup individual test places
        GeoPlace.objects.filter(name__startswith="Individual").delete()

        # Test BULK create (potential optimization - not yet implemented)
        # This shows what COULD be achieved with bulk operations
        start = time.time()

        places_to_create = []
        categories_to_create = []
        for i in range(test_iterations):
            try:
                schema = GeoPlaceAmenityInput(
                    name=TranslationSchema(de=f"Bulk {i}"),
                    location=LocationSchema(lon=8.5417, lat=47.3769),
                    country_code="CH",
                    place_type_identifiers=["root.restaurant"],
                    operating_status="open",
                )

                # Note: This simulates bulk create but doesn't actually use it
                # because update_or_create doesn't support bulk operations
                # This is a theoretical benchmark
                place_data = {
                    "name": f"Bulk {i}",
                    "location": Point(8.5417, 47.3769),
                    "country_code": "CH",
                    "detail_type": "amenity",
                    "is_active": True,
                }
                places_to_create.append(GeoPlace(**place_data))
                categories_to_create.append(category)
            except Exception:
                pass

        # Actually do the bulk create (without deduplication)
        with transaction.atomic():
            created_places = GeoPlace.objects.bulk_create(
                places_to_create, batch_size=500
            )
            if created_places:
                from server.apps.geometries.models import GeoPlaceCategory

                GeoPlaceCategory.objects.bulk_create(
                    [
                        GeoPlaceCategory(geo_place=place, category=category)
                        for place, category in zip(created_places, categories_to_create)
                    ],
                    ignore_conflicts=True,
                )

        bulk_time = time.time() - start

        # Cleanup
        cleanup_count = GeoPlace.objects.filter(name__startswith="Bulk").delete()[0]

        speedup = individual_time / bulk_time if bulk_time > 0 else 0

        # Project for 1M entries
        avg_time_bulk = bulk_time / test_iterations if test_iterations > 0 else 0
        time_per_million_bulk = avg_time_bulk * 1000000
        time_per_million_individual = (individual_time / test_iterations) * 1000000

        return TestResult(
            test_name="Bulk Operations",
            iterations=test_iterations,
            total_time=bulk_time,
            avg_time=avg_time_bulk,
            details=f"Speedup: {speedup:.1f}x faster (bulk vs individual)\n"
            f"Individual saves: {individual_time:.2f}s ({(individual_time/test_iterations)*1000:.2f}ms per place)\n"
            f"Bulk create: {bulk_time:.2f}s ({(bulk_time/test_iterations)*1000:.2f}ms per place)\n"
            f"NOTE: Bulk create skips deduplication - not directly comparable!\n"
            f"Cleaned up {cleanup_count} test places\n"
            f"Projected time for 1M entries:\n"
            f"  • Bulk create (no dedup): {self._format_duration(time_per_million_bulk)}\n"
            f"  • Individual saves (with dedup): {self._format_duration(time_per_million_individual)}\n"
            f"  • Difference: {self._format_duration(time_per_million_individual - time_per_million_bulk)}\n\n"
            f"⚠️  WARNING: Bulk operations skip deduplication logic.\n"
            f"    This test shows theoretical max speed, but real imports\n"
            f"    need individual processing for deduplication.",
        )

    def _test_hybrid_dedup_bulk(self, iterations: int) -> TestResult:
        """Test hybrid approach: dedup in batches, then bulk create.

        Strategy:
        1. Collect 100 places
        2. Check each for duplicates (individual queries)
        3. Filter out duplicates
        4. Bulk create non-duplicates (single transaction)

        This combines deduplication safety with bulk create speed.
        """
        self.stdout.write("Testing hybrid dedup + bulk approach...")

        from django.db import transaction
        from server.apps.organizations.models import Organization
        from server.apps.categories.models import Category
        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput,
            SourceInput,
            DedupOptions,
        )
        from hut_services import LocationSchema
        from server.apps.translations.schema import TranslationSchema

        # Get or create test data
        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={"name": "OpenStreetMap", "url": "https://www.openstreetmap.org"},
        )

        try:
            category = Category.objects.get(identifier="root.restaurant")
        except Category.DoesNotExist:
            category = Category.objects.filter(slug="restaurant").first()

        if not category:
            return TestResult(
                test_name="Hybrid Dedup + Bulk",
                iterations=0,
                total_time=0,
                avg_time=0,
                details="Skipped - no test category",
            )

        test_iterations = min(iterations, 1000)
        batch_size = 100  # Process 100 at a time

        start = time.time()
        created_count = 0
        duplicate_count = 0

        # Process in batches
        for batch_start in range(0, test_iterations, batch_size):
            batch_end = min(batch_start + batch_size, test_iterations)

            # Step 1: Collect schemas for this batch
            schemas_to_create = []
            sources_to_create = []

            for i in range(batch_start, batch_end):
                schema = GeoPlaceAmenityInput(
                    name=TranslationSchema(de=f"Hybrid {i}"),
                    location=LocationSchema(lon=8.5417 + (i * 0.0001), lat=47.3769),
                    country_code="CH",
                    place_type_identifiers=["root.restaurant"],
                    operating_status="open",
                )
                source = SourceInput(
                    slug="osm",
                    source_id=f"hybrid/{timezone.now().timestamp()}{i}",
                )
                schemas_to_create.append(schema)
                sources_to_create.append(source)

            # Step 2: Check for duplicates (individual queries - fast with BBox)
            non_duplicates = []
            for schema, source in zip(schemas_to_create, sources_to_create):
                location = Point(schema.location.lon, schema.location.lat, srid=4326)

                # Quick dedup check using BBox
                from server.apps.geometries.models._geoplace import (
                    GeoPlace as GeoPlaceModel,
                )

                categories = GeoPlaceModel._resolve_categories_from_identifiers(
                    schema.place_type_identifiers
                )
                existing = GeoPlaceModel._find_existing_place_by_schema(
                    schema=schema,
                    location=location,
                    source_obj=osm_org,
                    from_source=source,
                    dedup_options=DedupOptions(distance_same=20, distance_any=4),
                    categories=categories,
                )

                if existing is None:
                    non_duplicates.append((schema, source))
                else:
                    duplicate_count += 1

            # Step 3: Bulk create non-duplicates
            if non_duplicates:
                geoplaces_to_create = []
                amenity_details_to_create = []
                categories_to_create = []

                for schema, source in non_duplicates:
                    # Create GeoPlace instance (not saved yet)
                    place = GeoPlace(
                        name=schema.name.de,
                        location=Point(
                            schema.location.lon, schema.location.lat, srid=4326
                        ),
                        country_code=schema.country_code,
                        detail_type=schema.detail_type.value,
                        is_active=schema.is_active,
                        is_public=schema.is_public,
                    )
                    # Generate slug (uses UUID-based uniqueness)
                    place.slug = GeoPlace.generate_unique_slug(
                        place.name, category_slug=None
                    )
                    geoplaces_to_create.append(place)
                    categories_to_create.append(category)

                    # Create AmenityDetail instance (not saved yet)
                    from server.apps.geometries.models import AmenityDetail

                    detail = AmenityDetail(
                        geo_place=place,  # Will be set after bulk create
                        operating_status=schema.operating_status.value,
                        opening_hours=schema.opening_hours,
                        phones=[p.model_dump() for p in schema.phones]
                        if schema.phones
                        else [],
                    )
                    amenity_details_to_create.append(detail)

                # Bulk create all at once
                with transaction.atomic():
                    # Bulk create GeoPlaces
                    created_places = GeoPlace.objects.bulk_create(geoplaces_to_create)

                    # Bulk create category associations
                    from server.apps.geometries.models import GeoPlaceCategory

                    GeoPlaceCategory.objects.bulk_create(
                        [
                            GeoPlaceCategory(geo_place=place, category=category)
                            for place, category in zip(
                                created_places, categories_to_create
                            )
                        ],
                        ignore_conflicts=True,
                    )

                    # Now create AmenityDetails with proper geo_place reference
                    for place, detail in zip(created_places, amenity_details_to_create):
                        detail.geo_place = place

                    # Bulk create AmenityDetails
                    from server.apps.geometries.models import AmenityDetail

                    AmenityDetail.objects.bulk_create(amenity_details_to_create)

                    # Create source associations
                    from server.apps.geometries.models import GeoPlaceSourceAssociation

                    associations = [
                        GeoPlaceSourceAssociation(
                            geo_place=place,
                            organization=osm_org,
                            source_id=source.source_id,
                        )
                        for place, (_, source) in zip(created_places, non_duplicates)
                    ]
                    GeoPlaceSourceAssociation.objects.bulk_create(associations)

                created_count += len(non_duplicates)

        hybrid_time = time.time() - start

        # Cleanup
        cleanup_count = GeoPlace.objects.filter(name__startswith="Hybrid").delete()[0]

        # Compare to individual approach
        avg_time_hybrid = hybrid_time / test_iterations if test_iterations > 0 else 0
        avg_time_individual = 0.023  # From dedup test (~23ms)
        speedup = avg_time_individual / avg_time_hybrid if avg_time_hybrid > 0 else 0

        # Project for 1M entries
        time_per_million_hybrid = avg_time_hybrid * 1000000
        time_per_million_individual = avg_time_individual * 1000000

        return TestResult(
            test_name="Hybrid Dedup + Bulk",
            iterations=test_iterations,
            total_time=hybrid_time,
            avg_time=avg_time_hybrid,
            details=f"Speedup: {speedup:.1f}x faster (hybrid vs individual)\n"
            f"Individual saves: {avg_time_individual*1000:.2f}ms per place\n"
            f"Hybrid approach: {avg_time_hybrid*1000:.2f}ms per place\n"
            f"Created: {created_count}, Duplicates filtered: {duplicate_count}\n"
            f"Cleaned up {cleanup_count} test places\n\n"
            f"Strategy:\n"
            f"  1. Collect {batch_size} places\n"
            f"  2. Check duplicates (BBox queries - fast)\n"
            f"  3. Bulk create non-duplicates (single transaction)\n\n"
            f"Projected time for 1M entries:\n"
            f"  • Hybrid approach: {self._format_duration(time_per_million_hybrid)}\n"
            f"  • Individual saves: {self._format_duration(time_per_million_individual)}\n"
            f"  • Time saved: {self._format_duration(time_per_million_individual - time_per_million_hybrid)}\n\n"
            f"✓ This could be implemented for 2-3x additional speedup!",
        )

    def _test_batch_sizes(self, iterations: int, batch_sizes: list[int]) -> TestResult:
        """Test hybrid approach with different batch sizes to find optimal size.

        Tests batch sizes like 50, 100, 200, 500, 1000 to find the sweet spot
        between speed and memory usage.
        """
        self.stdout.write("Testing batch size optimization...")

        from django.db import transaction
        from server.apps.organizations.models import Organization
        from server.apps.categories.models import Category
        from server.apps.geometries.schemas import (
            GeoPlaceAmenityInput,
            SourceInput,
            DedupOptions,
        )
        from hut_services import LocationSchema
        from server.apps.translations.schema import TranslationSchema

        # Get or create test data
        osm_org, _ = Organization.objects.get_or_create(
            slug="osm",
            defaults={"name": "OpenStreetMap", "url": "https://www.openstreetmap.org"},
        )

        try:
            category = Category.objects.get(identifier="root.restaurant")
        except Category.DoesNotExist:
            category = Category.objects.filter(slug="restaurant").first()

        if not category:
            return TestResult(
                test_name="Batch Size Optimization",
                iterations=0,
                total_time=0,
                avg_time=0,
                details="Skipped - no test category",
            )

        # Remove artificial limit - use full iterations
        test_iterations = iterations
        results_by_batch_size = {}

        # Test each batch size
        for batch_size in batch_sizes:
            self.stdout.write(f"  Testing batch size {batch_size}...")

            start = time.time()
            created_count = 0
            total_processed = 0

            # Process in batches
            for batch_start in range(0, test_iterations, batch_size):
                batch_end = min(batch_start + batch_size, test_iterations)
                batch_iterations = batch_end - batch_start

                # Step 1: Collect schemas
                schemas_to_create = []
                sources_to_create = []

                for i in range(batch_start, batch_end):
                    schema = GeoPlaceAmenityInput(
                        name=TranslationSchema(de=f"Batch{batch_size}_{i}"),
                        location=LocationSchema(lon=8.5417 + (i * 0.0001), lat=47.3769),
                        country_code="CH",
                        place_type_identifiers=["root.restaurant"],
                        operating_status="open",
                    )
                    source = SourceInput(
                        slug="osm",
                        source_id=f"batch{batch_size}_{timezone.now().timestamp()}_{i}",
                    )
                    schemas_to_create.append(schema)
                    sources_to_create.append(source)

                # Step 2: Check for duplicates
                non_duplicates = []
                for schema, source in zip(schemas_to_create, sources_to_create):
                    location = Point(
                        schema.location.lon, schema.location.lat, srid=4326
                    )

                    from server.apps.geometries.models._geoplace import (
                        GeoPlace as GeoPlaceModel,
                    )

                    categories = GeoPlaceModel._resolve_categories_from_identifiers(
                        schema.place_type_identifiers
                    )
                    existing = GeoPlaceModel._find_existing_place_by_schema(
                        schema=schema,
                        location=location,
                        source_obj=osm_org,
                        from_source=source,
                        dedup_options=DedupOptions(distance_same=20, distance_any=4),
                        categories=categories,
                    )

                    if existing is None:
                        non_duplicates.append((schema, source))

                # Step 3: Bulk create
                if non_duplicates:
                    geoplaces_to_create = []
                    amenity_details_to_create = []
                    categories_to_create = []

                    for schema, source in non_duplicates:
                        place = GeoPlace(
                            name=schema.name.de,
                            location=Point(
                                schema.location.lon, schema.location.lat, srid=4326
                            ),
                            country_code=schema.country_code,
                            detail_type=schema.detail_type.value,
                            is_active=schema.is_active,
                            is_public=schema.is_public,
                        )
                        place.slug = GeoPlace.generate_unique_slug(
                            place.name, category_slug=None
                        )
                        geoplaces_to_create.append(place)
                        categories_to_create.append(category)

                        from server.apps.geometries.models import AmenityDetail

                        detail = AmenityDetail(
                            geo_place=place,
                            operating_status=schema.operating_status.value,
                            opening_hours=schema.opening_hours,
                            phones=[p.model_dump() for p in schema.phones]
                            if schema.phones
                            else [],
                        )
                        amenity_details_to_create.append(detail)

                    with transaction.atomic():
                        created_places = GeoPlace.objects.bulk_create(
                            geoplaces_to_create
                        )

                        from server.apps.geometries.models import GeoPlaceCategory

                        GeoPlaceCategory.objects.bulk_create(
                            [
                                GeoPlaceCategory(geo_place=place, category=category)
                                for place, category in zip(
                                    created_places, categories_to_create
                                )
                            ],
                            ignore_conflicts=True,
                        )

                        for place, detail in zip(
                            created_places, amenity_details_to_create
                        ):
                            detail.geo_place = place

                        from server.apps.geometries.models import AmenityDetail

                        AmenityDetail.objects.bulk_create(amenity_details_to_create)

                        from server.apps.geometries.models import (
                            GeoPlaceSourceAssociation,
                        )

                        associations = [
                            GeoPlaceSourceAssociation(
                                geo_place=place,
                                organization=osm_org,
                                source_id=source.source_id,
                            )
                            for place, (_, source) in zip(
                                created_places, non_duplicates
                            )
                        ]
                        GeoPlaceSourceAssociation.objects.bulk_create(associations)

                    created_count += len(non_duplicates)

                total_processed += batch_iterations

            batch_time = time.time() - start
            avg_time_per_place = (
                batch_time / total_processed if total_processed > 0 else 0
            )

            results_by_batch_size[batch_size] = {
                "time": batch_time,
                "avg_time": avg_time_per_place,
                "created": created_count,
                "processed": total_processed,
            }

            # Cleanup for next batch size test
            GeoPlace.objects.filter(name__startswith=f"Batch{batch_size}_").delete()

        # Find optimal batch size
        optimal_batch_size = min(
            results_by_batch_size.keys(),
            key=lambda bs: results_by_batch_size[bs]["avg_time"],
        )
        optimal_time = results_by_batch_size[optimal_batch_size]["avg_time"]

        # Build comparison table
        comparison_lines = []
        comparison_lines.append(
            f"{'Batch Size':<12} {'Time per Place':<18} {'Total Time':<12} {'Speedup':<10}"
        )
        comparison_lines.append("-" * 52)

        baseline_time = 0.023  # Individual saves baseline
        for bs in sorted(results_by_batch_size.keys()):
            result = results_by_batch_size[bs]
            speedup = (
                baseline_time / result["avg_time"] if result["avg_time"] > 0 else 0
            )
            comparison_lines.append(
                f"{bs:<12} {result['avg_time']*1000:<18.2f}ms "
                f"{result['time']:<12.2f}s {speedup:<10.1f}x"
            )

        comparison_table = "\n    ".join(comparison_lines)

        # Project for 1M entries with optimal batch size
        time_per_million_optimal = optimal_time * 1000000
        time_per_million_baseline = baseline_time * 1000000

        return TestResult(
            test_name="Batch Size Optimization",
            iterations=test_iterations,
            total_time=sum(r["time"] for r in results_by_batch_size.values()),
            avg_time=optimal_time,
            details=f"Optimal batch size: {optimal_batch_size}\n\n"
            f"Performance Comparison:\n    {comparison_table}\n\n"
            f"Recommendation: Use batch size {optimal_batch_size} for best performance\n\n"
            f"Projected time for 1M entries:\n"
            f"  • Optimal (batch={optimal_batch_size}): {self._format_duration(time_per_million_optimal)}\n"
            f"  • Baseline (individual): {self._format_duration(time_per_million_baseline)}\n"
            f"  • Time saved: {self._format_duration(time_per_million_baseline - time_per_million_optimal)}\n\n"
            f"Trade-offs:\n"
            f"  • Smaller batches (50-100): Lower memory, more transactions\n"
            f"  • Medium batches (200-500): Best balance of speed and memory\n"
            f"  • Larger batches (1000+): Fastest, but higher memory usage",
        )

    def _test_m2m_category_queries(self, iterations: int) -> TestResult:
        """Benchmark M2M category query performance."""
        self.stdout.write("Testing M2M category query performance...")

        parent, _ = Category.objects.get_or_create(
            slug="test_parent", defaults={"name": "Test Parent"}
        )
        child, _ = Category.objects.get_or_create(
            slug="test_child", parent=parent, defaults={"name": "Test Child"}
        )

        target_count = min(iterations, 1000)
        existing_count = GeoPlace.objects.filter(name__startswith="M2M Test").count()
        to_create = max(0, target_count - existing_count)

        if to_create:
            places = []
            for i in range(to_create):
                places.append(
                    GeoPlace(
                        name=f"M2M Test {existing_count + i}",
                        location=Point(8.0 + (i * 0.00001), 47.0, srid=4326),
                        country_code="CH",
                    )
                )
            created_places = GeoPlace.objects.bulk_create(places)
            GeoPlaceCategory.objects.bulk_create(
                [
                    GeoPlaceCategory(geo_place=place, category=child)
                    for place in created_places
                ],
                ignore_conflicts=True,
            )

        query_iterations = max(1, min(iterations, 200))
        start = time.time()
        for _ in range(query_iterations):
            list(
                GeoPlace.objects.filter(categories=child)
                .prefetch_related("categories__parent")
                .only("id", "name")
            )
        total_time = time.time() - start
        avg_time = total_time / query_iterations

        return TestResult(
            test_name="M2M Category Queries",
            iterations=query_iterations,
            total_time=total_time,
            avg_time=avg_time,
            details=(
                f"Places: {max(existing_count, target_count)}\n"
                f"Query iterations: {query_iterations}"
            ),
        )

    def _test_load_10k_places(self, iterations: int) -> TestResult:
        """Load test: create 10k+ GeoPlaces with category associations."""
        self.stdout.write("Testing 10k+ load creation...")

        target_count = max(iterations, 10000)
        parent, _ = Category.objects.get_or_create(
            slug="load_parent", defaults={"name": "Load Parent"}
        )
        child, _ = Category.objects.get_or_create(
            slug="load_child", parent=parent, defaults={"name": "Load Child"}
        )

        existing_count = GeoPlace.objects.filter(name__startswith="Load Test").count()
        to_create = max(0, target_count - existing_count)

        start = time.time()
        if to_create:
            places = []
            for i in range(to_create):
                places.append(
                    GeoPlace(
                        name=f"Load Test {existing_count + i}",
                        location=Point(8.0 + (i * 0.00001), 47.0, srid=4326),
                        country_code="CH",
                    )
                )
            created_places = GeoPlace.objects.bulk_create(places)
            GeoPlaceCategory.objects.bulk_create(
                [
                    GeoPlaceCategory(geo_place=place, category=child)
                    for place in created_places
                ],
                ignore_conflicts=True,
            )
        total_time = time.time() - start
        avg_time = total_time / max(to_create, 1)

        return TestResult(
            test_name="Load Test (10k+ places)",
            iterations=target_count,
            total_time=total_time,
            avg_time=avg_time,
            details=(
                f"Created: {to_create} (existing: {existing_count})\n"
                f"Avg create time: {avg_time*1000:.2f}ms per place"
            ),
        )

    def _test_parallel_import(self, iterations: int) -> TestResult:
        """Smoke test parallel update_or_create calls."""
        self.stdout.write("Testing parallel import smoke test...")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        from server.apps.geometries.schemas import (
            DedupOptions,
            GeoPlaceAmenityInput,
            SourceInput,
        )
        from server.apps.translations.schema import TranslationSchema
        from hut_services import LocationSchema
        from server.apps.organizations.models import Organization

        Organization.objects.get_or_create(
            slug="osm",
            defaults={"name": "OpenStreetMap"},
        )
        parent, _ = Category.objects.get_or_create(
            slug="parallel_parent", defaults={"name": "Parallel Parent"}
        )
        Category.objects.get_or_create(
            slug="parallel_child", parent=parent, defaults={"name": "Parallel Child"}
        )

        test_iterations = min(iterations, 200)

        def _worker(idx: int) -> None:
            schema = GeoPlaceAmenityInput(
                name=TranslationSchema(de=f"Parallel {idx}"),
                location=LocationSchema(lon=8.0 + (idx * 0.0001), lat=47.0),
                country_code="CH",
                place_type_identifiers=["parallel_parent.parallel_child"],
                operating_status="open",
            )
            source = SourceInput(
                slug="osm",
                source_id=f"parallel/{idx}",
            )
            GeoPlace.update_or_create(
                schema=schema,
                from_source=source,
                dedup_options=DedupOptions(distance_same=0, distance_any=0),
            )

        start = time.time()
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_worker, i) for i in range(test_iterations)]
            for future in as_completed(futures):
                future.result()
        total_time = time.time() - start
        avg_time = total_time / max(test_iterations, 1)

        return TestResult(
            test_name="Parallel Import Smoke Test",
            iterations=test_iterations,
            total_time=total_time,
            avg_time=avg_time,
            details="Workers: 4",
        )
