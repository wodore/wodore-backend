from __future__ import annotations

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from server.apps.geometries.schemas import AmenityDetailInput
from server.apps.geometries.models import GeoPlace
from server.core.models import TimeStampedModel
from server.core.utils import UpdateCreateStatus


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
    phones = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Phone Numbers"),
        help_text=_(
            "List of phone numbers: [{'number': '+41 123 456 78 90', 'label': 'Main'}]"
        ),
    )

    # Brand information
    brand = models.ForeignKey(
        "categories.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="amenity_brands",
        verbose_name=_("Brand"),
        help_text=_("Brand category (e.g., Volg, Migros, Coop)"),
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

    @classmethod
    def update_or_create(
        cls,
        place: "GeoPlace",
        schema: "AmenityDetailInput",
        protected_fields: set[str] | None = None,
    ) -> tuple["AmenityDetail", "UpdateCreateStatus"]:
        """
        Create or update an AmenityDetail for a GeoPlace.

        Args:
            place: GeoPlace instance
            schema: AmenityDetailInput schema with detail data
            protected_fields: Set of field names that should not be updated

        Returns:
            Tuple of (AmenityDetail instance, UpdateCreateStatus)

        Example:
            schema = AmenityDetailInput(
                operating_status="open",
                opening_hours={"mon": [["09:00", "18:00"]]},
                phones=[PhoneSchema(number="+41 123 456 789")],
            )
            detail, status = AmenityDetail.update_or_create(
                place=place,
                schema=schema,
                protected_fields={"phones"},
            )
        """
        from server.apps.categories.models import Category
        from server.core import UpdateCreateStatus

        protected = protected_fields or set()

        # Try to get existing detail
        try:
            detail = cls.objects.get(geo_place=place)
            is_new = False
        except cls.DoesNotExist:
            detail = cls(geo_place=place)
            is_new = True

        # Track if anything was updated
        updated = False
        update_fields = []

        # Update operating_status
        if "operating_status" not in protected:
            if detail.operating_status != schema.operating_status:
                detail.operating_status = schema.operating_status
                update_fields.append("operating_status")
                updated = True

        # Update opening_months
        if "opening_months" not in protected and schema.opening_months:
            if detail.opening_months != schema.opening_months:
                detail.opening_months = schema.opening_months
                update_fields.append("opening_months")
                updated = True

        # Update opening_hours
        if "opening_hours" not in protected and schema.opening_hours:
            if detail.opening_hours != schema.opening_hours:
                detail.opening_hours = schema.opening_hours
                update_fields.append("opening_hours")
                updated = True

        # Update phones
        if "phones" not in protected and schema.phones:
            new_phones = [
                p.model_dump() if hasattr(p, "model_dump") else p for p in schema.phones
            ]
            if detail.phones != new_phones:
                detail.phones = new_phones
                update_fields.append("phones")
                updated = True

        # Update brand
        if "brand" not in protected and schema.brand_slug:
            try:
                brand = Category.objects.get(slug=schema.brand_slug)
                if detail.brand != brand:
                    detail.brand = brand
                    update_fields.append("brand")
                    updated = True
            except Category.DoesNotExist:
                pass

        # Save the detail
        if is_new:
            detail.save()
            return detail, UpdateCreateStatus.created
        elif updated:
            detail.save(update_fields=update_fields)
            return detail, UpdateCreateStatus.updated
        else:
            return detail, UpdateCreateStatus.no_change
