"""Typed operating facts per place and mode.

OpenSpec ``geoplace-kinds-operations-graph`` (task 2.1): one row per
``(geo_place, mode)`` — the mode being a ``mode.*`` category — with a
nullable ``capacity`` (DB-constrained ≥ 0; semantics per kind: beds /
seats / visitors), structured per-mode ``opening_hours`` JSON and an
``extra`` JSON overflow. Invariant: capacity is per-MODE — imports
never emit two same-mode associations with differing capacities.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel


class GeoPlaceOperation(TimeStampedModel):
    """Typed operating facts of one place in one operation mode."""

    #: FK id attributes — plugin-less inference gap (pyrefly idiom).
    geo_place_id: int
    mode_id: int

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="operations",
        verbose_name=_("Geo Place"),
    )
    mode = models.ForeignKey(
        "categories.Category",
        on_delete=models.RESTRICT,
        db_index=True,
        related_name="place_operations",
        limit_choices_to={"parent__slug": "mode"},
        verbose_name=_("Mode"),
        help_text=_("Operation mode (mode.standard / mode.reduced)"),
    )
    capacity = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Capacity"),
        help_text=_(
            "Capacity of this mode (beds / seats / visitors — "
            "semantics per kind); unknown stays empty"
        ),
    )
    opening_hours = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Opening hours"),
        help_text=_("Structured weekly hours of this mode"),
    )
    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra"),
        help_text=_("Overflow data for this operation (JSON)"),
    )

    class Meta:
        verbose_name = _("Geo Place Operation")
        verbose_name_plural = _("Geo Place Operations")
        ordering = ["geo_place", "mode__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["geo_place", "mode"],
                name="geoplaceoperation_unique_place_mode",
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_capacity_nonnegative",
                condition=models.Q(capacity__isnull=True) | models.Q(capacity__gte=0),
            ),
        ]

    def __str__(self) -> str:
        capacity = f", {self.capacity}" if self.capacity is not None else ""
        return f"{self.geo_place_id} [{self.mode.identifier}]{capacity}"
