from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel
from server.core.managers import BaseManager


class Boundary(TimeStampedModel):
    """
    GeoNames Administrative Boundaries - raw imported polygon data.

    Contains unmodified GeoNames administrative boundaries and regions.
    Read-only in admin. Imported from shapes files and admin codes.
    """

    objects: BaseManager = BaseManager()

    # Primary identifier
    geoname_id = models.BigIntegerField(
        primary_key=True,
        verbose_name=_("GeoName ID"),
        help_text=_("Unique GeoNames identifier"),
    )

    # Names
    name = models.CharField(
        max_length=255,
        verbose_name=_("Name"),
        help_text=_("Name of area or region"),
        db_index=True,
    )

    # Feature classification
    feature_code = models.CharField(
        max_length=10,
        verbose_name=_("Feature Code"),
        help_text=_("GeoNames feature code"),
        db_index=True,
    )

    # Geographic data
    geometry = models.MultiPolygonField(
        srid=4326,
        verbose_name=_("Geometry"),
        help_text=_("Polygon boundaries (SRID 4326)"),
        spatial_index=True,
    )

    # Administrative data
    country_code = models.CharField(
        max_length=2,
        verbose_name=_("Country Code"),
        help_text=_("ISO-3166 country code"),
        db_index=True,
    )
    admin_level = models.SmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Admin Level"),
        help_text=_("Administrative level (1-4)"),
        db_index=True,
    )

    # Metadata
    modification_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Modification Date"),
        help_text=_("Last modification date from GeoNames"),
    )

    class Meta:
        verbose_name = _("Boundary")
        verbose_name_plural = _("Boundaries")
        ordering = ("name",)
        indexes = [
            models.Index(fields=["country_code", "admin_level"]),
            models.Index(fields=["feature_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.geoname_id})"
