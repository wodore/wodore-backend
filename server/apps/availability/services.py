"""
Service layer for availability tracking business logic.

This service encapsulates the complex orchestration of fetching and updating
availability data, making it reusable across management commands, API endpoints,
and background tasks.
"""

import datetime
from typing import NamedTuple

from django.conf import settings
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Cast
from django.db.models import CharField
from django.utils import timezone

from server.apps.huts.models import Hut, HutType
from server.apps.organizations.models import Organization

from .models import AvailabilityStatus, HutAvailability, HutAvailabilityHistory

SERVICES: dict = settings.SERVICES


class UpdateResult(NamedTuple):
    """Result of updating a single hut's availability"""

    hut_id: int
    hut_slug: str
    success: bool
    error_message: str | None = None
    records_created: int = 0
    records_updated: int = 0
    history_entries: int = 0


class BatchUpdateResult(NamedTuple):
    """Result of updating multiple huts' availability"""

    total_huts: int
    successful: int
    failed: int
    results: list[UpdateResult]


class AvailabilityService:
    """
    Service for managing hut availability updates.

    This service handles the complex orchestration of:
    1. Fetching booking data from external sources
    2. Processing and storing availability records
    3. Tracking update history
    4. Managing status tracking for all huts (including those with no data)
    """

    @staticmethod
    def fetch_from_external_service(
        hut_slugs: list[str],
        date: datetime.datetime | datetime.date | str = "now",
        days: int = 365,
        request_interval: float = 0.1,
        progress_callback: callable = None,
    ) -> list:
        """
        Fetch booking data from external services (original Hut.get_bookings logic).

        This method calls the external booking services to get live availability data.
        The request_interval controls the delay between requests to each individual hut.

        Args:
            hut_slugs: List of hut slugs to fetch
            date: Start date for bookings
            days: Number of days to fetch
            request_interval: Time between requests to external services for each hut

        Returns:
            List of HutBookingsSchema objects from external services
        """
        from hut_services.core.schema import (
            HutBookingsSchema as HutServiceBookingSchema,
        )
        from hut_services import HutTypeEnum
        from server.apps.huts.schemas_booking import HutBookingsSchema

        bookings: dict[int, HutServiceBookingSchema] = {}
        huts = []

        # Build base queryset with prefetch to avoid N+1 queries
        obj = Hut.objects.prefetch_related(
            "hut_type_open", "hut_type_closed", "availability_source_ref"
        )
        obj = obj.filter(slug__in=hut_slugs)

        # TODO: Future optimization - parallel service calls
        # If we have multiple booking services (hrs, sac, etc.), we could fetch them
        # concurrently using ThreadPoolExecutor or asyncio to reduce total fetch time.
        # Currently we only have one service, so this is sequential.
        for src_name, service in SERVICES.items():
            if service.support_booking:
                # Get source_ids for this specific service
                # Note: source_id is stored as CharField, so we get strings
                # The external service may return int keys, so we handle both
                service_source_ids = list(
                    obj.filter(orgs_source__organization__slug=src_name)
                    .values_list("orgs_source__source_id", flat=True)
                    .distinct()
                )

                # Skip if no source_ids for this service
                if not service_source_ids:
                    continue

                # Fetch bookings from service (service handles request_interval internally)
                # The service's get_bookings already handles progress per hut internally
                service_bookings = service.get_bookings(
                    date=date,
                    days=days,
                    source_ids=service_source_ids,
                    lang="de",
                    request_interval=request_interval,
                    progress_callback=progress_callback,  # Pass through for per-hut updates
                    cached=False,  # Disable cache to enable true batched fetching
                )
                bookings.update(service_bookings)

                # Only query huts if we got bookings back
                if service_bookings:
                    huts += list(
                        obj.filter(
                            orgs_source__organization__slug=src_name,
                            availability_source_ref__slug=src_name,
                            orgs_source__source_id__in=service_bookings.keys(),
                        )
                        .annotate(
                            # Cast source_id to string to ensure it's always a string type
                            # (CharField in model, but Django may return various types)
                            source_id=Cast(F("orgs_source__source_id"), CharField()),
                            source=Value(src_name),
                            hut_type_open_slug=F("hut_type_open__slug"),
                            hut_type_closed_slug=F("hut_type_closed__slug"),
                            capacity_open_total=F("capacity_open"),
                            capacity_closed_total=F("capacity_closed"),
                        )
                        .values(
                            "id",
                            "slug",
                            "source_id",
                            "location",
                            "hut_type_open_slug",
                            "hut_type_closed_slug",
                            "capacity_open_total",
                            "capacity_closed_total",
                            "source",
                        )
                    )

        for h in huts:
            # source_id from DB is a string (CharField), but external service may use int keys
            # Try both string and int lookup for compatibility
            source_id_str = h.get("source_id")
            booking = bookings.get(source_id_str)  # Try string key first
            if booking is None and source_id_str:
                # Try converting to int if string lookup failed
                try:
                    booking = bookings.get(int(source_id_str))
                except (ValueError, TypeError):
                    pass

            if booking is not None:
                for b in booking.bookings:
                    # Determine hut_type based on booking capacity
                    # Each hut can have two operational states with different capacities:
                    # - "open" state: standard/default operation (full capacity)
                    # - "closed" state: reduced operation (limited capacity)

                    capacity_open = h.get("capacity_open_total")
                    capacity_closed = h.get("capacity_closed_total")

                    # If both capacities are the same, use external info (b.unattended flag)
                    if (
                        capacity_open is not None
                        and capacity_closed is not None
                        and capacity_open == capacity_closed
                    ):
                        # Same capacity for both states - rely on external unattended flag
                        if b.unattended and h.get("hut_type_closed_slug") is not None:
                            b.hut_type = h["hut_type_closed_slug"]
                        else:
                            b.hut_type = (
                                h.get("hut_type_open_slug") or HutTypeEnum.unknown.value
                            )
                    # Use capacity to determine state: fewer beds = closed, more beds = open
                    elif (
                        capacity_closed is not None
                        and capacity_closed > 0
                        and b.places.total <= capacity_closed
                        and h.get("hut_type_closed_slug") is not None
                    ):
                        # Booking total is at or below closed capacity → reduced/closed state
                        b.hut_type = h["hut_type_closed_slug"]
                    # Default: open state (includes unknown status, no closed type, etc.)
                    else:
                        # Fall back to open (default), or unknown if open is also None
                        b.hut_type = (
                            h.get("hut_type_open_slug") or HutTypeEnum.unknown.value
                        )

                h.update(booking)
                # Ensure source_id is always a string (may come as int from DB)
                if "source_id" in h and h["source_id"] is not None:
                    h["source_id"] = str(h["source_id"])
        return [HutBookingsSchema(**h) for h in huts]

    @staticmethod
    def update_huts_availability(
        huts: list[Hut],
        days: int = 365,
        request_interval: float = 0.1,
        fetch_progress_callback: callable = None,
        process_progress_callback: callable = None,
        batch_size: int = 30,  # Fetch and process N huts per batch
        update_history_last_checked: bool = True,  # Enable for accurate duration tracking
    ) -> BatchUpdateResult:
        """
        Update availability data for multiple huts with batched external fetching.

        This method fetches and processes huts in batches to:
        - Reduce memory usage (only hold one batch at a time)
        - Reduce load on external servers (spread requests over time)
        - Improve fault tolerance (save progress as we go)
        - Start saving data sooner (faster time-to-first-result)

        Args:
            huts: List of Hut instances to update
            days: Number of days to fetch availability for (default: 365)
            request_interval: Time in seconds between requests to external service for each hut (default: 0.1)
            fetch_progress_callback: Optional callback function to call after each hut is fetched from external service
            process_progress_callback: Optional callback function to call after each hut is processed and saved to database
            batch_size: Number of huts to fetch and process per batch (default: 30)
            update_history_last_checked: Whether to update history.last_checked for unchanged records (default: False for performance)

        Returns:
            BatchUpdateResult with overall statistics and individual results
        """
        if not huts:
            return BatchUpdateResult(
                total_huts=0,
                successful=0,
                failed=0,
                results=[],
            )

        results = []
        successful_huts = []
        failed_huts = []
        now = timezone.now()

        # Process huts in batches: fetch batch → process batch → repeat
        for i in range(0, len(huts), batch_size):
            batch_huts = huts[i : i + batch_size]
            batch_hut_slugs = [hut.slug for hut in batch_huts]

            # Fetch booking data for this batch only
            try:
                bookings_data = AvailabilityService.fetch_from_external_service(
                    hut_slugs=batch_hut_slugs,
                    date="now",
                    days=days,
                    request_interval=request_interval,
                    progress_callback=fetch_progress_callback,
                )
            except Exception as fetch_error:
                # If fetch fails for this batch, mark all batch huts as failed
                for hut in batch_huts:
                    status, _ = AvailabilityStatus.objects.get_or_create(
                        hut=hut, defaults={"last_checked": now}
                    )
                    status.mark_failure()
                    failed_huts.append(hut)
                    results.append(
                        UpdateResult(
                            hut_id=hut.id,
                            hut_slug=hut.slug,
                            success=False,
                            error_message=f"Batch fetch error: {str(fetch_error)}",
                        )
                    )
                    if process_progress_callback is not None:
                        process_progress_callback()
                # Continue with next batch
                continue

            # Group batch huts with their booking data
            batch_huts_with_data = []
            for hut in batch_huts:
                hut_booking = next(
                    (b for b in bookings_data if b.slug == hut.slug), None
                )

                if not hut_booking or not hut_booking.bookings:
                    # Track for bulk failure update
                    failed_huts.append(hut)
                    results.append(
                        UpdateResult(
                            hut_id=hut.id,
                            hut_slug=hut.slug,
                            success=False,
                            error_message="No booking data returned",
                        )
                    )
                    if process_progress_callback is not None:
                        process_progress_callback()
                else:
                    batch_huts_with_data.append((hut, hut_booking))

            # Process this batch (single database transaction for the batch)
            if batch_huts_with_data:
                try:
                    batch_results = AvailabilityService._process_huts_batch(
                        batch=batch_huts_with_data,
                        now=now,
                        update_history_last_checked=update_history_last_checked,
                    )

                    for result in batch_results:
                        results.append(result)
                        if result.success:
                            # Find hut object for status tracking
                            hut = next(
                                h
                                for h, _ in batch_huts_with_data
                                if h.id == result.hut_id
                            )
                            successful_huts.append(hut)
                        else:
                            hut = next(
                                h
                                for h, _ in batch_huts_with_data
                                if h.id == result.hut_id
                            )
                            failed_huts.append(hut)

                        if process_progress_callback is not None:
                            process_progress_callback()

                except Exception as e:
                    # Mark entire batch as failed
                    for hut, hut_booking in batch_huts_with_data:
                        failed_huts.append(hut)
                        results.append(
                            UpdateResult(
                                hut_id=hut.id,
                                hut_slug=hut.slug,
                                success=False,
                                error_message=f"Batch processing error: {str(e)}",
                            )
                        )
                        if process_progress_callback is not None:
                            process_progress_callback()

        # Bulk update AvailabilityStatus for all huts
        if successful_huts or failed_huts:
            all_huts = successful_huts + failed_huts
            hut_ids = [h.id for h in all_huts]

            # Get or create all status objects
            existing_statuses = {
                status.hut_id: status
                for status in AvailabilityStatus.objects.filter(hut_id__in=hut_ids)
            }

            statuses_to_create = []
            statuses_to_update = []

            # Update successful huts
            for hut in successful_huts:
                if hut.id in existing_statuses:
                    status = existing_statuses[hut.id]
                    status.last_checked = now
                    status.last_success = now
                    status.has_data = True
                    status.consecutive_failures = 0
                    statuses_to_update.append(status)
                else:
                    statuses_to_create.append(
                        AvailabilityStatus(
                            hut=hut,
                            last_checked=now,
                            last_success=now,
                            has_data=True,
                            consecutive_failures=0,
                        )
                    )

            # Update failed huts
            for hut in failed_huts:
                if hut.id in existing_statuses:
                    status = existing_statuses[hut.id]
                    status.last_checked = now
                    status.consecutive_failures += 1
                    statuses_to_update.append(status)
                else:
                    statuses_to_create.append(
                        AvailabilityStatus(
                            hut=hut,
                            last_checked=now,
                            consecutive_failures=1,
                        )
                    )

            # Bulk create/update
            if statuses_to_create:
                AvailabilityStatus.objects.bulk_create(statuses_to_create)

            if statuses_to_update:
                AvailabilityStatus.objects.bulk_update(
                    statuses_to_update,
                    fields=[
                        "last_checked",
                        "last_success",
                        "has_data",
                        "consecutive_failures",
                    ],
                )

        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        return BatchUpdateResult(
            total_huts=len(huts),
            successful=successful,
            failed=failed,
            results=results,
        )

    @staticmethod
    def _process_huts_batch(
        batch: list[tuple[Hut, any]],
        now: timezone.datetime = None,
        update_history_last_checked: bool = False,
    ) -> list[UpdateResult]:
        """
        Process multiple huts in a single transaction for better performance.

        This significantly reduces lock contention and memory usage by processing
        multiple huts together instead of one transaction per hut.

        Args:
            batch: List of (hut, hut_booking) tuples to process together
            now: Shared timestamp for consistency

        Returns:
            List of UpdateResult objects, one per hut
        """
        if now is None:
            now = timezone.now()

        results = []

        # Pre-fetch organizations for all huts in batch
        org_slugs = {hut_booking.source for _, hut_booking in batch}
        orgs_by_slug = {
            org.slug: org for org in Organization.objects.filter(slug__in=org_slugs)
        }

        # Collect all dates and hut IDs for bulk queries
        all_hut_ids = [hut.id for hut, _ in batch]
        all_dates = []
        for _, hut_booking in batch:
            all_dates.extend([booking.date for booking in hut_booking.bookings])

        # Pre-fetch all HutTypes needed for this batch
        unique_hut_types = set()
        for _, hut_booking in batch:
            for booking in hut_booking.bookings:
                if booking.hut_type:
                    unique_hut_types.add(booking.hut_type)

        hut_type_cache = {}
        if unique_hut_types:
            for hut_type_slug in unique_hut_types:
                try:
                    hut_type_cache[hut_type_slug] = HutType.values.get(hut_type_slug)
                except HutType.DoesNotExist:
                    hut_type_cache[hut_type_slug] = None

        # Use a single transaction for the entire batch
        with transaction.atomic():
            # Bulk fetch all existing availabilities for all huts in the batch
            # CRITICAL: Use select_related to avoid N+1 queries on foreign keys
            existing_availabilities = HutAvailability.objects.filter(
                hut_id__in=all_hut_ids, availability_date__in=all_dates
            ).select_related("hut", "source_organization", "hut_type")

            # Index by (hut_id, date) for fast lookup
            availability_index = {
                (avail.hut_id, avail.availability_date): avail
                for avail in existing_availabilities
            }

            # Prepare bulk operation lists
            all_new_availabilities = []
            all_new_history_entries = []
            all_availabilities_to_update = []
            all_availabilities_unchanged = []
            all_unchanged_availability_ids = []

            # Process each hut in the batch
            for hut, hut_booking in batch:
                source_org = orgs_by_slug.get(hut_booking.source)
                if not source_org:
                    results.append(
                        UpdateResult(
                            hut_id=hut.id,
                            hut_slug=hut.slug,
                            success=False,
                            error_message=f"Organization '{hut_booking.source}' not found",
                        )
                    )
                    continue

                source_hut_id = str(hut_booking.source_id)
                created_count = 0
                updated_count = 0

                # Process each booking for this hut
                for booking in hut_booking.bookings:
                    reservation_status = (
                        booking.reservation_status.value
                        if hasattr(booking.reservation_status, "value")
                        else str(booking.reservation_status)
                    )
                    occupancy_status = (
                        booking.occupancy_status.value
                        if hasattr(booking.occupancy_status, "value")
                        else str(booking.occupancy_status)
                    )
                    hut_type_obj = (
                        hut_type_cache.get(booking.hut_type)
                        if booking.hut_type
                        else None
                    )

                    availability = availability_index.get((hut.id, booking.date))

                    if availability is None:
                        # Create new availability record
                        new_avail = HutAvailability(
                            hut=hut,
                            availability_date=booking.date,
                            source_organization=source_org,
                            source_id=source_hut_id,
                            free=booking.free,
                            total=booking.total,
                            occupancy_percent=booking.occupancy_percent,
                            occupancy_steps=booking.occupancy_steps,
                            occupancy_status=occupancy_status,
                            reservation_status=reservation_status,
                            link=booking.link or "",
                            hut_type=hut_type_obj,
                            first_checked=now,
                            last_checked=now,
                        )
                        all_new_availabilities.append(new_avail)
                        created_count += 1
                    else:
                        # Check if data changed
                        changed = (
                            availability.free != booking.free
                            or availability.total != booking.total
                            or availability.hut_type != hut_type_obj
                            or availability.reservation_status != reservation_status
                        )

                        if changed:
                            # Record to history
                            all_new_history_entries.append(
                                HutAvailabilityHistory(
                                    availability=availability,
                                    hut=hut,
                                    availability_date=availability.availability_date,
                                    free=booking.free,
                                    total=booking.total,
                                    occupancy_percent=booking.occupancy_percent,
                                    occupancy_status=occupancy_status,
                                    reservation_status=reservation_status,
                                    hut_type=hut_type_obj,
                                    first_checked=now,
                                    last_checked=now,
                                )
                            )

                            # Update current state
                            availability.free = booking.free
                            availability.total = booking.total
                            availability.occupancy_percent = booking.occupancy_percent
                            availability.occupancy_steps = booking.occupancy_steps
                            availability.occupancy_status = occupancy_status
                            availability.reservation_status = reservation_status
                            availability.link = booking.link or ""
                            availability.hut_type = hut_type_obj
                            availability.last_checked = now

                            all_availabilities_to_update.append(availability)
                            updated_count += 1
                        else:
                            # No change - just update last_checked
                            availability.last_checked = now
                            all_availabilities_unchanged.append(availability)
                            all_unchanged_availability_ids.append(availability.id)

                results.append(
                    UpdateResult(
                        hut_id=hut.id,
                        hut_slug=hut.slug,
                        success=True,
                        records_created=created_count,
                        records_updated=updated_count,
                        history_entries=0,  # Will be counted after bulk create
                    )
                )

            # Bulk create new availability records
            if all_new_availabilities:
                created_availabilities = HutAvailability.objects.bulk_create(
                    all_new_availabilities
                )

                # Create initial history entries for new records
                for avail in created_availabilities:
                    all_new_history_entries.append(
                        HutAvailabilityHistory(
                            availability=avail,
                            hut=avail.hut,
                            availability_date=avail.availability_date,
                            free=avail.free,
                            total=avail.total,
                            occupancy_percent=avail.occupancy_percent,
                            occupancy_status=avail.occupancy_status,
                            reservation_status=avail.reservation_status,
                            hut_type=avail.hut_type,
                            first_checked=avail.first_checked,
                            last_checked=avail.last_checked,
                        )
                    )

            # Bulk update changed availability records
            if all_availabilities_to_update:
                HutAvailability.objects.bulk_update(
                    all_availabilities_to_update,
                    fields=[
                        "free",
                        "total",
                        "occupancy_percent",
                        "occupancy_steps",
                        "occupancy_status",
                        "reservation_status",
                        "link",
                        "hut_type",
                        "last_checked",
                    ],
                )

            # Bulk update unchanged availability records
            if all_availabilities_unchanged:
                HutAvailability.objects.bulk_update(
                    all_availabilities_unchanged,
                    fields=["last_checked"],
                )

            # Bulk create history entries
            if all_new_history_entries:
                HutAvailabilityHistory.objects.bulk_create(all_new_history_entries)

                # Update history counts in results
                history_by_hut = {}
                for entry in all_new_history_entries:
                    history_by_hut[entry.hut_id] = (
                        history_by_hut.get(entry.hut_id, 0) + 1
                    )

                for result in results:
                    if result.success and result.hut_id in history_by_hut:
                        # Update the result with history count
                        results[results.index(result)] = UpdateResult(
                            hut_id=result.hut_id,
                            hut_slug=result.hut_slug,
                            success=result.success,
                            records_created=result.records_created,
                            records_updated=result.records_updated,
                            history_entries=history_by_hut[result.hut_id],
                        )

            # Update history last_checked for unchanged records
            # This tracks how long each state has been stable (duration tracking)
            if update_history_last_checked and all_unchanged_availability_ids:
                from django.db import connection

                # Raw SQL is necessary here because Django ORM doesn't support DISTINCT ON efficiently
                # This single query updates ~50k records in 1-2 seconds vs minutes with ORM
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE availability_hutavailabilityhistory
                        SET last_checked = %s
                        WHERE id IN (
                            SELECT DISTINCT ON (availability_id, availability_date) id
                            FROM availability_hutavailabilityhistory
                            WHERE availability_id = ANY(%s)
                              AND availability_date = ANY(%s)
                            ORDER BY availability_id, availability_date, first_checked DESC
                        )
                        """,
                        [
                            now,
                            list(all_unchanged_availability_ids),
                            list(set(all_dates)),
                        ],
                    )

        return results

    @staticmethod
    def _process_hut_bookings(
        hut: Hut, hut_booking, now: timezone.datetime = None
    ) -> UpdateResult:
        """
        Process booking data for a single hut and store in database.

        Internal method used by update_huts_availability.
        Uses bulk operations for better performance.
        """
        source_org = Organization.objects.get(slug=hut_booking.source)
        source_hut_id = str(hut_booking.source_id)

        created_count = 0
        updated_count = 0
        history_count = 0
        if now is None:
            now = timezone.now()

        # Use a single transaction for all operations on this hut
        with transaction.atomic():
            # Get all existing availability records for this hut for the date range
            booking_dates = [booking.date for booking in hut_booking.bookings]
            existing_availabilities = {
                avail.availability_date: avail
                for avail in HutAvailability.objects.filter(
                    hut=hut, availability_date__in=booking_dates
                ).select_for_update()
            }

            # Pre-fetch all HutType objects to avoid N+1 queries
            unique_hut_types = {
                booking.hut_type for booking in hut_booking.bookings if booking.hut_type
            }
            hut_type_cache = {}
            if unique_hut_types:
                for hut_type_slug in unique_hut_types:
                    try:
                        hut_type_cache[hut_type_slug] = HutType.values.get(
                            hut_type_slug
                        )
                    except HutType.DoesNotExist:
                        hut_type_cache[hut_type_slug] = None

            # Get existing history records for unchanged availabilities (bulk fetch)
            unchanged_availability_ids = []

            # Prepare lists for bulk operations
            new_availabilities = []
            new_history_entries = []
            availabilities_to_update = []
            availabilities_unchanged = []

            # Process each booking date
            for booking in hut_booking.bookings:
                # Extract all fields from HutBookingSchema
                reservation_status = (
                    booking.reservation_status.value
                    if hasattr(booking.reservation_status, "value")
                    else str(booking.reservation_status)
                )
                occupancy_status = (
                    booking.occupancy_status.value
                    if hasattr(booking.occupancy_status, "value")
                    else str(booking.occupancy_status)
                )

                # Get hut_type FK object from cache
                hut_type_obj = (
                    hut_type_cache.get(booking.hut_type) if booking.hut_type else None
                )

                availability = existing_availabilities.get(booking.date)

                if availability is None:
                    # Create new availability record
                    new_avail = HutAvailability(
                        hut=hut,
                        availability_date=booking.date,
                        source_organization=source_org,
                        source_id=source_hut_id,
                        free=booking.free,
                        total=booking.total,
                        occupancy_percent=booking.occupancy_percent,
                        occupancy_steps=booking.occupancy_steps,
                        occupancy_status=occupancy_status,
                        reservation_status=reservation_status,
                        link=booking.link or "",
                        hut_type=hut_type_obj,
                        first_checked=now,
                        last_checked=now,
                    )
                    new_availabilities.append(new_avail)
                else:
                    # Check if data changed (inline to avoid extra method calls)
                    changed = (
                        availability.free != booking.free
                        or availability.total != booking.total
                        or availability.hut_type != hut_type_obj
                        or availability.reservation_status != reservation_status
                    )

                    if changed:
                        # Record to history before updating
                        new_history_entries.append(
                            HutAvailabilityHistory(
                                availability=availability,
                                hut=hut,
                                availability_date=availability.availability_date,
                                free=booking.free,
                                total=booking.total,
                                occupancy_percent=booking.occupancy_percent,
                                occupancy_status=occupancy_status,
                                reservation_status=reservation_status,
                                hut_type=hut_type_obj,
                                first_checked=now,
                                last_checked=now,
                            )
                        )

                        # Update current state
                        availability.free = booking.free
                        availability.total = booking.total
                        availability.occupancy_percent = booking.occupancy_percent
                        availability.occupancy_steps = booking.occupancy_steps
                        availability.occupancy_status = occupancy_status
                        availability.reservation_status = reservation_status
                        availability.link = booking.link or ""
                        availability.hut_type = hut_type_obj
                        availability.last_checked = now

                        availabilities_to_update.append(availability)
                        updated_count += 1
                    else:
                        # No change - just update last_checked
                        availability.last_checked = now
                        availabilities_unchanged.append(availability)
                        unchanged_availability_ids.append(availability.id)

            # Bulk create new availability records
            if new_availabilities:
                created_availabilities = HutAvailability.objects.bulk_create(
                    new_availabilities
                )
                created_count = len(created_availabilities)

                # Create initial history entries for new records
                for avail in created_availabilities:
                    new_history_entries.append(
                        HutAvailabilityHistory(
                            availability=avail,
                            hut=hut,
                            availability_date=avail.availability_date,
                            free=avail.free,
                            total=avail.total,
                            occupancy_percent=avail.occupancy_percent,
                            occupancy_status=avail.occupancy_status,
                            reservation_status=avail.reservation_status,
                            hut_type=avail.hut_type,
                            first_checked=avail.first_checked,
                            last_checked=avail.last_checked,
                        )
                    )

            # Bulk update changed availability records
            if availabilities_to_update:
                HutAvailability.objects.bulk_update(
                    availabilities_to_update,
                    fields=[
                        "free",
                        "total",
                        "occupancy_percent",
                        "occupancy_steps",
                        "occupancy_status",
                        "reservation_status",
                        "link",
                        "hut_type",
                        "last_checked",
                    ],
                )

            # Bulk update unchanged availability records (only last_checked)
            if availabilities_unchanged:
                HutAvailability.objects.bulk_update(
                    availabilities_unchanged,
                    fields=["last_checked"],
                )

            # Bulk create history entries
            if new_history_entries:
                HutAvailabilityHistory.objects.bulk_create(new_history_entries)
                history_count = len(new_history_entries)

            # Bulk update history last_checked for unchanged records
            if unchanged_availability_ids:
                # Get the most recent history entry for each unchanged availability
                # Use a subquery to get only the latest history per availability
                latest_history = (
                    HutAvailabilityHistory.objects.filter(
                        availability_id__in=unchanged_availability_ids,
                        availability_date__in=booking_dates,
                    )
                    .order_by("availability_id", "-first_checked")
                    .distinct("availability_id")
                )

                # Bulk update last_checked on history entries
                HutAvailabilityHistory.objects.filter(
                    id__in=[h.id for h in latest_history]
                ).update(last_checked=now)

        # Note: AvailabilityStatus is now updated in bulk by the calling method
        # to avoid N individual database writes

        return UpdateResult(
            hut_id=hut.id,
            hut_slug=hut.slug,
            success=True,
            records_created=created_count,
            records_updated=updated_count,
            history_entries=history_count,
        )

    @staticmethod
    def update_hut_availability(
        hut: Hut,
        days: int = 365,
        request_interval: float = 0.1,
    ) -> UpdateResult:
        """
        Update availability data for a single hut.

        Note: This is a convenience wrapper around update_huts_availability for single huts.
        For better performance when updating multiple huts, use update_huts_availability directly.

        Args:
            hut: The Hut instance to update
            days: Number of days to fetch availability for (default: 365)
            request_interval: Time in seconds between requests (default: 0.1)

        Returns:
            UpdateResult with success status and statistics
        """
        batch_result = AvailabilityService.update_huts_availability(
            huts=[hut],
            days=days,
            request_interval=request_interval,
        )
        return (
            batch_result.results[0]
            if batch_result.results
            else UpdateResult(
                hut_id=hut.id,
                hut_slug=hut.slug,
                success=False,
                error_message="No result returned from batch update",
            )
        )
