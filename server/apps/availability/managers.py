import datetime

from django.db import models
from django.utils import timezone

from server.core.managers import BaseManager


class AvailabilityStatusManager(BaseManager):
    """Custom manager for AvailabilityStatus"""

    pass


class HutAvailabilityManager(BaseManager):
    """Custom manager for HutAvailability with priority-based query methods"""

    def needing_update(
        self,
        high_priority_minutes: int = 30,
        medium_priority_minutes: int = 180,  # 3 hours
        low_priority_minutes: int = 1440,  # 24 hours
        inactive_priority_minutes: int = 10080,  # 7 days
    ) -> models.QuerySet:
        """
        Return huts that need updating based on priority rules.

        Priority levels:
        - High: Active, full/nearly-full dates in next 14 days (check every 30 min)
        - Medium: Active, moderate occupancy in next 14 days (check every 3 hours)
        - Low: Active, mostly empty availability (check daily)
        - Inactive: Inactive huts (check weekly)
        - Never checked: Always include new huts
        """
        now = timezone.now()
        high_threshold = now - datetime.timedelta(minutes=high_priority_minutes)
        medium_threshold = now - datetime.timedelta(minutes=medium_priority_minutes)
        low_threshold = now - datetime.timedelta(minutes=low_priority_minutes)

        next_14_days = now.date() + datetime.timedelta(days=14)

        # Exclude closed huts (free == 0 and total == 0) from active priority
        active_huts = self.exclude(free=0, total=0)

        # High priority: Active, full or high occupancy (>75%) in next 14 days
        high_priority = active_huts.filter(
            availability_date__gte=now.date(),
            availability_date__lte=next_14_days,
            last_checked__lt=high_threshold,
            occupancy_percent__gt=75.0,  # >75% occupied
        )

        # Medium priority: Active, medium occupancy (25-75%) in next 14 days
        # Exclude empty huts
        medium_priority = active_huts.filter(
            availability_date__gte=now.date(),
            availability_date__lte=next_14_days,
            last_checked__lt=medium_threshold,
            occupancy_percent__gt=25.0,
            occupancy_percent__lte=75.0,
        ).exclude(free=models.F("total"))  # Exclude empty

        # Low priority: Active, low occupancy (<=25%) in next 14 days
        # Include closed huts here
        low_priority = self.filter(
            availability_date__gte=now.date(),
            availability_date__lte=next_14_days,
            last_checked__lt=low_threshold,
            occupancy_percent__lte=25.0,
        )

        # Combine and return distinct huts
        # Note: We get distinct hut IDs to avoid fetching same hut multiple times
        return (high_priority | medium_priority | low_priority).distinct()

    def for_date_range(
        self,
        hut_id: int | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
        days: int | None = None,
    ) -> models.QuerySet:
        """
        Optimized query for date range views (map and detail).

        Args:
            hut_id: If provided, filter to specific hut (detail view)
            date_from: Start date (defaults to today)
            date_to: End date (optional if days is provided)
            days: Number of days from date_from (defaults to 14)

        Either date_to or days must be provided. If both are None, defaults to 14 days.
        If both are provided, date_to takes precedence.
        """
        if date_from is None:
            date_from = timezone.now().date()

        if date_to is None:
            if days is None:
                days = 14
            date_to = date_from + datetime.timedelta(days=days)

        qs = self.filter(
            availability_date__gte=date_from,
            availability_date__lt=date_to,
        )

        if hut_id is not None:
            qs = qs.filter(hut_id=hut_id)

        return qs.select_related("hut", "source_organization", "hut_type").order_by(
            "hut", "availability_date"
        )

    def get_huts_needing_update(
        self,
        high_priority_minutes: int = 30,
        medium_priority_minutes: int = 180,
        low_priority_minutes: int = 1440,
        inactive_priority_minutes: int = 10080,  # 7 days
    ) -> models.QuerySet:
        """
        Get distinct Hut objects that need updating.

        Returns huts that either:
        1. Have availability data and need updates based on priority
        2. Have AvailabilityStatus and need rechecking (even if they returned empty before)
        3. Have booking_ref but have never been checked (no AvailabilityStatus yet)

        This ensures:
        - Regular updates of huts with data
        - Periodic rechecking of huts that previously had no data
        - Discovery of new huts
        """
        # Import here to avoid circular dependency
        from server.apps.huts.models import Hut
        from .models import AvailabilityStatus

        now = timezone.now()

        # 1. Get huts with availability data that need updates (priority-based)
        needing_update = self.needing_update(
            high_priority_minutes=high_priority_minutes,
            medium_priority_minutes=medium_priority_minutes,
            low_priority_minutes=low_priority_minutes,
            inactive_priority_minutes=inactive_priority_minutes,
        )
        existing_hut_ids = needing_update.values_list("hut_id", flat=True).distinct()
        huts_with_data = Hut.objects.filter(id__in=existing_hut_ids)

        # 2. Get huts with AvailabilityStatus that need rechecking
        # Use inactive_priority (7 days) for huts that returned empty/failed
        inactive_threshold = now - datetime.timedelta(minutes=inactive_priority_minutes)
        status_needing_check = AvailabilityStatus.objects.filter(
            last_checked__lt=inactive_threshold
        ).values_list("hut_id", flat=True)
        huts_needing_recheck = Hut.objects.filter(
            id__in=status_needing_check,
            booking_ref__isnull=False,
        )

        # 3. Get new huts with booking_ref that have never been checked
        all_bookable_huts = Hut.objects.filter(booking_ref__isnull=False)
        checked_hut_ids = AvailabilityStatus.objects.values_list("hut_id", flat=True)
        new_huts = all_bookable_huts.exclude(id__in=checked_hut_ids)

        # Combine all three groups
        return (huts_with_data | huts_needing_recheck | new_huts).distinct()


class HutAvailabilityHistoryManager(BaseManager):
    """Custom manager for HutAvailabilityHistory"""

    def for_trend(
        self,
        hut_id: int,
        target_date: datetime.date,
        days_before: int = 30,
    ) -> models.QuerySet:
        """
        Get historical trend data for a specific date.
        Shows how availability for target_date evolved over time.
        """
        lookback_date = timezone.now().date() - datetime.timedelta(days=days_before)

        return (
            self.filter(
                hut_id=hut_id,
                availability_date=target_date,
                first_checked__gte=lookback_date,
            )
            .select_related("hut")
            .order_by("first_checked")
        )
