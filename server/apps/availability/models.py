from model_utils.models import TimeStampedModel

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


from server.apps.huts.models import Hut, HutType
from server.apps.organizations.models import Organization

from .managers import (
    AvailabilityStatusManager,
    HutAvailabilityHistoryManager,
    HutAvailabilityManager,
)


class AvailabilityStatus(TimeStampedModel):
    """
    Tracks the availability tracking status for each hut.
    This ensures we record when a hut was last checked, even if no availability data was returned.

    Use cases:
    - Huts that are inactive in external booking systems (return empty data)
    - Tracking last check time to determine update priority
    - Preventing repeated failed attempts to fetch unavailable huts
    """

    objects: AvailabilityStatusManager = AvailabilityStatusManager()

    hut = models.OneToOneField(
        Hut,
        on_delete=models.CASCADE,
        related_name="availability_status",
        verbose_name=_("Hut"),
        primary_key=True,
    )
    last_checked = models.DateTimeField(
        verbose_name=_("Last Checked"),
        help_text=_("When availability was last fetched for this hut"),
        db_index=True,
    )
    last_success = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Successful Fetch"),
        help_text=_("When availability data was last successfully retrieved"),
    )
    has_data = models.BooleanField(
        default=False,
        verbose_name=_("Has Availability Data"),
        help_text=_("Whether this hut has ever returned availability data"),
    )
    consecutive_failures = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_("Consecutive Failures"),
        help_text=_("Number of consecutive times the fetch returned no data or failed"),
    )

    class Meta:
        verbose_name = _("Availability Status")
        verbose_name_plural = _("Availability Statuses")
        ordering = ("-last_checked",)

    def __str__(self) -> str:
        return f"{self.hut.name} - Last checked: {self.last_checked}"

    def mark_success(self):
        """Mark successful data fetch"""
        now = timezone.now()
        self.last_checked = now
        self.last_success = now
        self.has_data = True
        self.consecutive_failures = 0
        self.save()

    def mark_failure(self):
        """Mark failed or empty data fetch"""
        self.last_checked = timezone.now()
        self.consecutive_failures += 1
        self.save()


class HutAvailability(TimeStampedModel):
    """
    Current availability state for huts.
    One row per hut per date, stores the latest known availability.
    Optimized for fast reads (map queries, detail views).
    """

    objects: HutAvailabilityManager = HutAvailabilityManager()

    hut = models.ForeignKey(
        Hut,
        on_delete=models.CASCADE,
        related_name="availabilities",
        verbose_name=_("Hut"),
        db_index=False,  # Index defined in Meta.indexes
    )
    source_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="hut_availabilities",
        verbose_name=_("Source Organization"),
        help_text=_("Organization providing the booking data"),
        db_index=False,  # Index defined in Meta.indexes
    )
    source_id = models.CharField(
        max_length=100,
        verbose_name=_("Source ID"),
        help_text=_("Hut ID in the source organization's system"),
    )
    availability_date = models.DateField(
        verbose_name=_("Availability Date"),
        help_text=_("Date for which this availability data applies"),
        db_index=True,
    )

    # Raw booking data from source (matching HutBookingSchema)
    free = models.PositiveSmallIntegerField(
        verbose_name=_("Free Places"),
        help_text=_("Number of available places"),
    )
    total = models.PositiveSmallIntegerField(
        verbose_name=_("Total Places"),
        help_text=_("Total number of places"),
    )

    # Computed fields from HutBookingSchema (stored for fast retrieval)
    occupancy_percent = models.FloatField(
        verbose_name=_("Occupancy Percent"),
        help_text=_("Occupancy percentage (0-100)"),
    )
    occupancy_steps = models.PositiveSmallIntegerField(
        verbose_name=_("Occupancy Steps"),
        help_text=_("Occupancy in discrete steps (0-100, increments of 10)"),
    )
    occupancy_status = models.CharField(
        max_length=20,
        verbose_name=_("Occupancy Status"),
        help_text=_("Status: empty, low, medium, high, full, unknown"),
    )
    reservation_status = models.CharField(
        max_length=20,
        verbose_name=_("Reservation Status"),
        help_text=_("Status: unknown, possible, not_possible, not_online"),
    )

    # Additional fields
    link = models.URLField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("Booking Link"),
    )
    hut_type = models.ForeignKey(
        HutType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="availabilities",
        verbose_name=_("Hut Type"),
        help_text=_("Hut type on this date (open/closed)"),
    )

    # Metadata - timestamps
    first_checked = models.DateTimeField(
        verbose_name=_("First Checked"),
        help_text=_("When this availability was first recorded"),
        db_index=True,
    )
    last_checked = models.DateTimeField(
        verbose_name=_("Last Checked"),
        help_text=_("When this hut was last queried"),
        db_index=True,
    )

    class Meta:
        verbose_name = _("Hut Availability")
        verbose_name_plural = _("Hut Availabilities")
        ordering = ("availability_date", "hut__name")
        indexes = [
            models.Index(fields=["hut", "availability_date"]),
            models.Index(fields=["source_organization", "availability_date"]),
            models.Index(fields=["availability_date", "last_checked"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["hut", "availability_date"],
                name="unique_hut_date",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.hut.name} - {self.availability_date} ({self.free}/{self.total})"

    def has_changed(
        self, free: int, total: int, hut_type: HutType | None = None
    ) -> bool:
        """Check if availability data has changed"""
        changed = self.free != free or self.total != total
        if hut_type is not None:
            changed = changed or self.hut_type != hut_type
        return changed

    def record_change(
        self,
        free: int,
        total: int,
        occupancy_percent: float = 0.0,
        occupancy_status: str = "unknown",
        reservation_status: str = "unknown",
        hut_type: HutType | None = None,
    ) -> "HutAvailabilityHistory":
        """
        Record a change to history.
        Creates a new history entry. Previous entry's last_checked was already
        updated to now on every check while data was unchanged.
        """
        now = timezone.now()

        # Create new history entry (minimal fields only)
        history = HutAvailabilityHistory.objects.create(
            availability=self,
            hut=self.hut,
            availability_date=self.availability_date,
            free=free,
            total=total,
            occupancy_percent=occupancy_percent,
            occupancy_status=occupancy_status,
            reservation_status=reservation_status,
            hut_type=hut_type,
            first_checked=now,
            last_checked=now,
        )
        return history

    def update_availability(
        self,
        free: int,
        total: int,
        occupancy_percent: float = 0.0,
        occupancy_steps: int = 0,
        occupancy_status: str = "unknown",
        reservation_status: str = "unknown",
        link: str = "",
        hut_type: HutType | None = None,
    ) -> tuple[bool, "HutAvailabilityHistory | None"]:
        """
        Update availability with change detection.
        Returns (changed, history_entry).
        """
        now = timezone.now()
        changed = self.has_changed(free, total, hut_type)
        history = None

        if changed:
            # Record to history before updating
            history = self.record_change(
                free=free,
                total=total,
                occupancy_percent=occupancy_percent,
                occupancy_status=occupancy_status,
                reservation_status=reservation_status,
                hut_type=hut_type,
            )
            # Update current state
            self.free = free
            self.total = total
            self.occupancy_percent = occupancy_percent
            self.occupancy_steps = occupancy_steps
            self.occupancy_status = occupancy_status
            self.reservation_status = reservation_status
            self.link = link
            self.hut_type = hut_type
            self.last_checked = now
            self.save()
        else:
            # No change in data, just update last_checked on current state and history
            self.last_checked = now
            self.save(update_fields=["last_checked"])

            current_history = (
                HutAvailabilityHistory.objects.filter(
                    availability=self, availability_date=self.availability_date
                )
                .order_by("-first_checked")
                .first()
            )
            if current_history:
                current_history.last_checked = now
                current_history.save(update_fields=["last_checked"])

        return changed, history


class HutAvailabilityHistory(TimeStampedModel):
    """
    Append-only log of availability changes.
    Only records when availability actually changes (not every check).
    Tracks state duration using first_checked and last_checked timestamps.
    """

    objects: HutAvailabilityHistoryManager = HutAvailabilityHistoryManager()

    availability = models.ForeignKey(
        HutAvailability,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="history",
        verbose_name=_("Availability"),
    )
    hut = models.ForeignKey(
        Hut,
        on_delete=models.CASCADE,
        related_name="availability_history",
        verbose_name=_("Hut"),
        db_index=False,  # Index defined in Meta.indexes
    )
    availability_date = models.DateField(
        verbose_name=_("Availability Date"),
        help_text=_("Target date this availability applies to"),
        db_index=True,
    )

    # Snapshot of availability state - minimal fields for history
    free = models.PositiveSmallIntegerField(
        verbose_name=_("Free Places"),
    )
    total = models.PositiveSmallIntegerField(
        verbose_name=_("Total Places"),
    )

    # Computed fields for trend analysis
    occupancy_percent = models.FloatField(
        verbose_name=_("Occupancy Percent"),
    )
    occupancy_status = models.CharField(
        max_length=20,
        verbose_name=_("Occupancy Status"),
        help_text=_("Status: empty, low, medium, high, full, unknown"),
    )
    reservation_status = models.CharField(
        max_length=20,
        verbose_name=_("Reservation Status"),
        help_text=_("Status: unknown, possible, not_possible, not_online"),
    )

    # Metadata
    hut_type = models.ForeignKey(
        HutType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="availability_history",
        verbose_name=_("Hut Type"),
        help_text=_("Hut type on this date (open/closed)"),
    )

    # Timestamp tracking for state duration
    first_checked = models.DateTimeField(
        verbose_name=_("First Checked"),
        help_text=_("When this state was first observed"),
        db_index=True,
    )
    last_checked = models.DateTimeField(
        verbose_name=_("Last Checked"),
        help_text=_("When this state was last confirmed (updated on every check)"),
    )

    class Meta:
        verbose_name = _("Hut Availability History")
        verbose_name_plural = _("Hut Availability Histories")
        ordering = ("-first_checked",)
        indexes = [
            models.Index(fields=["hut", "availability_date", "first_checked"]),
            models.Index(fields=["availability_date", "first_checked"]),
        ]

    def __str__(self) -> str:
        return f"{self.hut.name} - {self.availability_date} ({self.free}/{self.total}) @ {self.first_checked}"

    @property
    def duration_seconds(self) -> float:
        """Calculate how long this state lasted in seconds"""
        return (self.last_checked - self.first_checked).total_seconds()
