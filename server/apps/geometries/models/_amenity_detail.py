from __future__ import annotations

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from server.core.models import TimeStampedModel


class OperatingStatus(models.TextChoices):
    """Operating status for amenities."""

    OPEN = "open", _("Open")
    TEMPORARILY_CLOSED = "temporarily_closed", _("Temporarily Closed")
    PERMANENTLY_CLOSED = "permanently_closed", _("Permanently Closed")
    UNKNOWN = "unknown", _("Unknown")


class MonthStatus(models.TextChoices):
    """Monthly availability status."""

    YES = "yes", _("Yes")
    YESISH = "yesish", _("Mostly Yes")
    MAYBE = "maybe", _("Maybe")
    NOISH = "noish", _("Mostly No")
    NO = "no", _("No")
    UNKNOWN = "unknown", _("Unknown")


class AmenityDetail(TimeStampedModel):
    """
    Detailed information for amenity places.

    Covers food supplies, shops, restaurants, emergency services,
    and accommodation amenities.
    """

    # OneToOne relationship to GeoPlace
    geo_place = models.OneToOneField(
        "GeoPlace",
        on_delete=models.CASCADE,
        related_name="amenity_detail",
        db_index=True,
        verbose_name=_("Geo Place"),
    )

    # Operating status
    operating_status = models.CharField(
        max_length=25,
        choices=OperatingStatus.choices,
        default=OperatingStatus.UNKNOWN,
        db_index=True,
        verbose_name=_("Operating Status"),
        help_text=_("Current operating status"),
    )

    # Monthly availability
    opening_months = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Opening Months"),
        help_text=_(
            "Monthly availability per month: "
            "{'jan': 'yes', 'feb': 'yes', ..., 'dec': 'no'}"
        ),
    )

    # Weekly opening hours
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Opening Hours"),
        help_text=_(
            "Structured weekly hours per weekday + public holidays. "
            "Example: {'mon': [['09:00', '12:00'], ['14:00', '18:00']], "
            "'tue': [['09:00', '12:00'], ['14:00', '18:00']], ..., 'public_holidays': 'closed'}"
        ),
    )

    # Contact information
    websites = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Websites"),
        help_text=_(
            "List of URLs with optional labels: [{'url': 'https://...', 'label': 'Official'}]"
        ),
    )

    phones = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Phone Numbers"),
        help_text=_(
            "List of phone numbers: [{'number': '+41 123 456 78 90', 'label': 'Main'}]"
        ),
    )

    class Meta:
        verbose_name = _("Amenity Detail")
        verbose_name_plural = _("Amenity Details")
        indexes = [
            models.Index(fields=["operating_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_operating_status_valid",
                condition=models.Q(
                    operating_status__in=[
                        "open",
                        "temporarily_closed",
                        "permanently_closed",
                        "unknown",
                    ]
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"Amenity detail for {self.geo_place.name_i18n}"

    def get_opening_status_for_month(self, month: int) -> str:
        """
        Get opening status for a specific month (1-12).

        Args:
            month: Month number (1 = January, ..., 12 = December)

        Returns:
            Month status string (yes/yesish/maybe/noish/no/unknown)
        """
        month_names = [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
        if 1 <= month <= 12:
            return self.opening_months.get(month_names[month - 1], MonthStatus.UNKNOWN)
        return MonthStatus.UNKNOWN

    def set_opening_status_for_month(self, month: int, status: str) -> None:
        """
        Set opening status for a specific month (1-12).

        Args:
            month: Month number (1 = January, ..., 12 = December)
            status: Month status string (yes/yesish/maybe/noish/no/unknown)
        """
        month_names = [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
        if 1 <= month <= 12:
            if not self.opening_months:
                self.opening_months = {}
            self.opening_months[month_names[month - 1]] = status
            self.save(update_fields=["opening_months"])
