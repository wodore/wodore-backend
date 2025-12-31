"""
Service layer for availability tracking business logic.

This service encapsulates the complex orchestration of fetching and updating
availability data, making it reusable across management commands, API endpoints,
and background tasks.
"""

from typing import NamedTuple

from django.db import transaction
from django.utils import timezone

from server.apps.huts.models import Hut, HutType
from server.apps.organizations.models import Organization

from .models import AvailabilityStatus, HutAvailability, HutAvailabilityHistory


class UpdateResult(NamedTuple):
    """Result of updating a single hut's availability"""

    success: bool
    error_message: str | None = None
    records_created: int = 0
    records_updated: int = 0
    history_entries: int = 0


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
    def update_hut_availability(
        hut: Hut,
        days: int = 365,
        request_interval: float = 0.1,
    ) -> UpdateResult:
        """
        Update availability data for a single hut.

        Args:
            hut: The Hut instance to update
            days: Number of days to fetch availability for (default: 365)
            request_interval: Time in seconds between requests (default: 0.1)

        Returns:
            UpdateResult with success status and statistics
        """
        try:
            # Fetch booking data using Hut.get_bookings
            try:
                bookings_data = Hut.get_bookings(
                    hut_slugs=[hut.slug],
                    date="now",
                    days=days,
                    request_interval=request_interval,
                )
            except Exception as booking_error:
                # Mark failure in AvailabilityStatus
                now = timezone.now()
                status, _ = AvailabilityStatus.objects.get_or_create(
                    hut=hut, defaults={"last_checked": now}
                )
                status.mark_failure()
                return UpdateResult(
                    success=False,
                    error_message=f"Error fetching bookings: {str(booking_error)}",
                )

            # Handle empty results
            if not bookings_data:
                # Mark failure in AvailabilityStatus (empty data)
                now = timezone.now()
                status, _ = AvailabilityStatus.objects.get_or_create(
                    hut=hut, defaults={"last_checked": now}
                )
                status.mark_failure()
                return UpdateResult(
                    success=False,
                    error_message="No booking data returned (empty result)",
                )

            # Process booking data
            hut_booking = bookings_data[0]
            source_org = Organization.objects.get(slug=hut_booking.source)
            source_hut_id = str(hut_booking.hut_id)

            created_count = 0
            updated_count = 0
            history_count = 0

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

                # Get hut_type FK object
                hut_type_obj = None
                if booking.hut_type:
                    hut_type_obj = HutType.values.get(booking.hut_type)

                now = timezone.now()

                # Get or create with atomic transaction
                with transaction.atomic():
                    availability, created = HutAvailability.objects.get_or_create(
                        hut=hut,
                        availability_date=booking.date,
                        defaults={
                            "source_organization": source_org,
                            "source_id": source_hut_id,
                            "free": booking.free,
                            "total": booking.total,
                            "occupancy_percent": booking.occupancy_percent,
                            "occupancy_steps": booking.occupancy_steps,
                            "occupancy_status": occupancy_status,
                            "reservation_status": reservation_status,
                            "link": booking.link or "",
                            "hut_type": hut_type_obj,
                            "first_checked": now,
                            "last_checked": now,
                        },
                    )

                    if created:
                        created_count += 1
                        # Create initial history entry (minimal fields only)
                        HutAvailabilityHistory.objects.create(
                            availability=availability,
                            hut=hut,
                            availability_date=booking.date,
                            free=booking.free,
                            total=booking.total,
                            occupancy_percent=booking.occupancy_percent,
                            occupancy_status=occupancy_status,
                            reservation_status=reservation_status,
                            hut_type=hut_type_obj,
                            first_checked=now,
                            last_checked=now,
                        )
                        history_count += 1
                    else:
                        # Check if data changed
                        changed, history = availability.update_availability(
                            free=booking.free,
                            total=booking.total,
                            occupancy_percent=booking.occupancy_percent,
                            occupancy_steps=booking.occupancy_steps,
                            occupancy_status=occupancy_status,
                            reservation_status=reservation_status,
                            link=booking.link or "",
                            hut_type=hut_type_obj,
                        )
                        if changed:
                            updated_count += 1
                            if history:
                                history_count += 1

            # Mark success in AvailabilityStatus
            now = timezone.now()
            status, _ = AvailabilityStatus.objects.get_or_create(
                hut=hut, defaults={"last_checked": now}
            )
            status.mark_success()

            return UpdateResult(
                success=True,
                records_created=created_count,
                records_updated=updated_count,
                history_entries=history_count,
            )

        except Exception as e:
            return UpdateResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
            )
