# from django.db import models
from computedfields.models import ComputedFieldsModel

from server.core.models import TimeStampedModel
from modeltrans.manager import MultilingualManager

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from server.apps.images.models import Image
from server.apps.organizations.models import Organization


class GeoPlaceImageAssociation(TimeStampedModel):
    image = models.ForeignKey(
        Image, on_delete=models.CASCADE, db_index=True, related_name="geoplace_details"
    )
    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="image_associations",
    )
    order = models.PositiveSmallIntegerField(blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.geo_place} <> {self.image}"

    class Meta:
        verbose_name = _("Image and Geo Place Association")
        ordering = ("geo_place__name", "order")
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["image", "geo_place"],
            ),
        )


class GeoPlaceSourceAssociation(TimeStampedModel, ComputedFieldsModel):
    objects = MultilingualManager()

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="geoplace_sources",
        db_index=True,
    )
    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="source_associations",
    )
    source_props = models.JSONField(
        help_text=_("Source properties."), blank=True, default=dict
    )
    source_id = models.CharField(
        max_length=100, blank=True, null=True, default="", help_text="Source id"
    )

    import_date = models.DateTimeField(auto_now_add=True)
    confidence = models.FloatField(
        default=1.0, help_text="Confidence in this source match (0-1)"
    )

    class Meta:
        verbose_name = _("Geo Place and Organization Association")
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["organization", "geo_place"],
            ),
        )

    def __str__(self) -> str:
        return f"{self.geo_place} <> {self.organization}"
