from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from server.core.models import TimeStampedModel
from computedfields.models import ComputedFieldsModel
from modeltrans.manager import MultilingualManager

from server.apps.images.models import Image
from server.apps.organizations.models import Organization


class UpdatePolicy(models.TextChoices):
    """How a source may update records."""

    ALWAYS = "always", _("Always overwrite all fields")
    MERGE = "merge", _("Skip fields edited by wodore source")
    PROTECTED = "protected", _("Never overwrite")
    AUTO_PROTECT = "auto_protect", _("Merge until wodore.modified_date, then protected")


class DeletePolicy(models.TextChoices):
    """What happens when a source no longer includes a record."""

    DEACTIVATE = "deactivate", _("Set is_active=False")
    KEEP = "keep", _("Ignore deletion")
    DELETE = "delete", _("Hard delete")
    AUTO_KEEP = "auto_keep", _("Deactivate until wodore.modified_date, then keep")


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
        max_length=100,
        blank=True,
        null=True,
        default="",
        help_text="Source id",
        db_index=True,  # Add index for faster lookups in import_geoplaces
    )

    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Extra"),
        help_text=_("Source-specific overflow data (JSON)"),
    )

    import_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(
        auto_now=False,
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Last time this source updated the record"),
    )
    confidence = models.FloatField(
        default=1.0, help_text="Confidence in this source match (0-1)"
    )

    # Import policies
    update_policy = models.CharField(
        max_length=20,
        choices=UpdatePolicy.choices,
        default=UpdatePolicy.AUTO_PROTECT,
        verbose_name=_("Update Policy"),
        help_text=_("How this source may update the record"),
    )

    delete_policy = models.CharField(
        max_length=20,
        choices=DeletePolicy.choices,
        default=DeletePolicy.AUTO_KEEP,
        verbose_name=_("Delete Policy"),
        help_text=_("What happens when this source no longer includes the record"),
    )

    priority = models.PositiveSmallIntegerField(
        default=10,
        db_index=True,
        verbose_name=_("Priority"),
        help_text=_("Source precedence for field conflicts (lower number wins)"),
    )

    class Meta:
        verbose_name = _("Geo Place and Organization Association")
        indexes = [
            models.Index(fields=["priority"]),
        ]
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_relationships",
                fields=["organization", "geo_place"],
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_update_policy_valid",
                condition=models.Q(
                    update_policy__in=["always", "merge", "protected", "auto_protect"]
                ),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_delete_policy_valid",
                condition=models.Q(
                    delete_policy__in=["deactivate", "keep", "delete", "auto_keep"]
                ),
            ),
        )

    def __str__(self) -> str:
        return f"{self.geo_place} <> {self.organization}"


class GeoPlaceExternalLink(models.Model):
    """
    Through-model connecting GeoPlaces to ExternalLinks.

    Allows the same ExternalLink to be associated with multiple GeoPlaces
    with different ordering.
    """

    geo_place = models.ForeignKey(
        "GeoPlace",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="link_associations",
        verbose_name=_("Geo Place"),
    )

    external_link = models.ForeignKey(
        "external_links.ExternalLink",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="place_associations",
        verbose_name=_("External Link"),
    )

    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        verbose_name=_("Order"),
        help_text=_("Display order for this link"),
    )

    class Meta:
        verbose_name = _("Geo Place Link")
        verbose_name_plural = _("Geo Place Links")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["geo_place", "order"]),
            models.Index(fields=["external_link"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["geo_place", "external_link"],
                name="%(app_label)s_%(class)s_unique_place_link",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.geo_place.name_i18n} → {self.external_link.label_i18n}"
