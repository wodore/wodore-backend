from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseManager


class Feature(models.Model):
    """
    GeoNames Feature Codes - curated configuration table.

    Maps GeoNames feature codes to our domain model.
    Only features with is_enabled=True are imported into GeoPlace.
    """

    objects: BaseManager = BaseManager()

    # GeoNames feature class choices
    class FeatureClass(models.TextChoices):
        A = "A", _("A · Administrative")
        H = "H", _("H · Hydrographic")
        L = "L", _("L · Area")
        P = "P", _("P · Populated Place")
        R = "R", _("R · Road / Railroad")
        S = "S", _("S · Spot Feature")
        T = "T", _("T · Terrain")
        U = "U", _("U · Undersea")
        V = "V", _("V · Vegetation")

    # Primary key: feature_class.feature_code (e.g., "T.PK", "S.RSTN")
    id = models.CharField(
        max_length=12,  # 1 char class + 1 dot + 10 char code
        primary_key=True,
        verbose_name=_("Feature ID"),
        help_text=_("Feature identifier: feature_class.feature_code (e.g., T.PK)"),
    )

    # GeoNames identifiers (stored separately for readability)
    feature_class = models.CharField(
        max_length=1,
        choices=FeatureClass.choices,
        verbose_name=_("Feature Class"),
        help_text=_("GeoNames feature class (e.g., T, S, P)"),
        db_index=True,
    )
    feature_code = models.CharField(
        max_length=10,
        verbose_name=_("Feature Code"),
        help_text=_("GeoNames feature code (e.g., PK, RSTN)"),
    )

    # Display information
    name = models.CharField(
        max_length=255,
        verbose_name=_("Name"),
        help_text=_("Official name of the feature type"),
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
        help_text=_("Optional description from GeoNames"),
    )

    # Configuration
    is_enabled = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Enabled"),
        help_text=_("Only enabled features are imported into GeoPlace"),
    )
    category = models.ForeignKey(
        "categories.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("Category"),
        help_text=_("Category mapping for import to GeoPlace"),
    )
    importance = models.SmallIntegerField(
        default=25,
        verbose_name=_("Importance"),
        help_text=_("Base importance for this feature type (0-100 scale, default: 25)"),
    )

    # Manual curation
    notes = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Notes"),
        help_text=_("Internal notes for manual curation"),
    )

    class Meta:
        verbose_name = _("GeoNames Feature")
        verbose_name_plural = _("GeoNames Features")
        ordering = ("id",)
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_feature_class_valid",
                condition=models.Q(
                    feature_class__in=["A", "H", "L", "P", "R", "S", "T", "U", "V"]
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["feature_class"]),
            models.Index(fields=["is_enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.feature_class}.{self.feature_code} - {self.name}"
