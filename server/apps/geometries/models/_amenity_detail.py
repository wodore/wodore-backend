from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from ._base_detail import GeoPlaceDetailBase

if TYPE_CHECKING:
    from server.apps.geometries.models import GeoPlace
    from server.apps.geometries.schemas import GeoPlaceAmenityInput, PartyInput
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


class AmenityDetail(GeoPlaceDetailBase):
    """
    Detailed information for amenity places.

    Covers food supplies, shops, restaurants, emergency services,
    and accommodation amenities.
    """

    # Fields to track for modification
    _trackable_fields = [
        "operating_status",
        "opening_months",
        "opening_hours",
    ]

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
                self.opening_months = dict[str, str]()
            self.opening_months[month_names[month - 1]] = status
            self.save(update_fields=["opening_months"])

    @classmethod
    def _write_party_associations(
        cls, place: GeoPlace, parties: list[PartyInput]
    ) -> bool:
        """Write schema party associations onto the place (idempotent).

        Mirrors ``GeoPlaceParty.clean()`` validation: an unknown or
        non-``role.*`` identifier raises ``ValueError`` instead of being
        silently dropped. Returns True when a new association was
        created. Shared by ``update_or_create`` and the GeoPlace-level
        schema create/update paths.
        """
        from server.apps.categories.models import Category
        from server.apps.parties.models import Party

        from . import GeoPlaceParty

        created_any = False
        for entry in parties:
            role = Category.objects.filter(identifier=entry.role).first()
            if role is None or role.parent_id is None or role.parent.slug != "role":
                raise ValueError(f"Invalid party role identifier: {entry.role}")
            party_defaults: dict[str, object] = {
                "name": entry.name or entry.slug.replace("_", " ").title(),
            }
            if entry.review_status:
                party_defaults["review_status"] = entry.review_status
            party, _created = Party.objects.get_or_create(
                slug=entry.slug, defaults=party_defaults
            )
            _assoc, assoc_created = GeoPlaceParty.objects.get_or_create(
                geo_place=place, party=party, role=role
            )
            created_any = created_any or assoc_created
        return created_any

    @classmethod
    def update_or_create(
        cls,
        place: GeoPlace,
        schema: GeoPlaceAmenityInput,
        protected_fields: set[str] | None = None,
    ) -> tuple[AmenityDetail, UpdateCreateStatus]:
        """
        Create or update an AmenityDetail for a GeoPlace.

        Args:
            place: GeoPlace instance
            schema: GeoPlaceAmenityInput schema with detail data
            protected_fields: Set of field names that should not be updated

        Returns:
            Tuple of (AmenityDetail instance, UpdateCreateStatus)

        Example:
            from server.apps.geometries.schemas import GeoPlaceAmenityInput

            schema = GeoPlaceAmenityInput(
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
        from server.core import UpdateCreateStatus

        # Import schema here to avoid circular import during model loading

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
        if (
            "operating_status" not in protected
            and schema.operating_status is not None
            and detail.operating_status != schema.operating_status
        ):
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

        # phones retired (external-link-uris): written as uri.phone
        # external links on the place — no detail-row write path
        # Update party associations (place-level; replaces the former
        # brand FK — parties attach to the place, not the detail row)
        if "parties" not in protected and schema.parties:
            if cls._write_party_associations(place, schema.parties):
                updated = True

        # Save the detail (without tracking modifications - this is an import)
        if is_new:
            detail.save(track_modifications=False)
            return detail, UpdateCreateStatus.created
        elif updated:
            if update_fields:
                detail.save(update_fields=update_fields, track_modifications=False)
            return detail, UpdateCreateStatus.updated
        else:
            return detail, UpdateCreateStatus.no_change
