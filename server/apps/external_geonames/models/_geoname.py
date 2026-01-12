from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel
from server.core.managers import BaseManager


class GeoName(TimeStampedModel):
    """
    GeoNames Place Data - raw imported point data.

    Contains unmodified GeoNames point data. Read-only in admin.
    Imported from country-specific files and enriched with alternate names
    via the AlternativeName model.
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
        help_text=_("Primary name from GeoNames"),
        db_index=True,
    )
    ascii_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("ASCII Name"),
        help_text=_("ASCII variant of name"),
    )

    # Feature classification - foreign key to Feature
    feature = models.ForeignKey(
        "external_geonames.Feature",
        on_delete=models.PROTECT,
        related_name="geonames",
        verbose_name=_("Feature"),
        help_text=_("GeoNames feature type"),
        db_index=True,
    )

    # Hierarchy - parent relationship
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Parent"),
        help_text=_("Parent GeoName in hierarchy"),
        db_index=True,
    )
    hierarchy_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name=_("Hierarchy Type"),
        help_text=_("Type of hierarchy relationship (e.g., 'ADM' for administrative)"),
    )

    # Geographic data
    location = models.PointField(
        srid=4326,
        verbose_name=_("Location"),
        help_text=_("Geographic coordinates (SRID 4326)"),
        spatial_index=True,
    )
    elevation = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Elevation"),
        help_text=_("Elevation in meters"),
    )

    # Demographics
    population = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Population"),
        help_text=_("Population count (if applicable)"),
    )

    # Administrative divisions
    country_code = models.CharField(
        max_length=2,
        verbose_name=_("Country Code"),
        help_text=_("ISO-3166 country code"),
        db_index=True,
    )
    admin1_code = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("Admin1 Code"),
        help_text=_("First-level administrative division"),
    )
    admin2_code = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name=_("Admin2 Code"),
        help_text=_("Second-level administrative division"),
    )
    admin3_code = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("Admin3 Code"),
        help_text=_("Third-level administrative division"),
    )
    admin4_code = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("Admin4 Code"),
        help_text=_("Fourth-level administrative division"),
    )

    # Metadata
    timezone = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name=_("Timezone"),
        help_text=_("Timezone identifier"),
    )
    modification_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Modification Date"),
        help_text=_("GeoNames modification date"),
    )
    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Deleted"),
        help_text=_("Marked as deleted in GeoNames"),
    )

    class Meta:
        verbose_name = _("GeoName")
        verbose_name_plural = _("GeoNames")
        ordering = ("name",)
        indexes = [
            models.Index(fields=["feature", "country_code"]),
            models.Index(fields=["is_deleted"]),
            GinIndex(
                fields=["name"],
                name="geonames_geoname_name_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.geoname_id})"
