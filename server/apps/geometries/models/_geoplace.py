from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import GinIndex, GistIndex
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from modeltrans.fields import TranslationField
from django_countries.fields import CountryField

from server.apps.categories.models import Category
from server.apps.images.models import Image
from server.apps.organizations.models import Organization
from server.core.models import TimeStampedModel


class GeoPlace(TimeStampedModel):
    """
    Canonical, curated geographic place.
    Can aggregate data from multiple sources (GeoNames, OSM, manual edits).
    """

    # TODO: add index which starts at 10000 or UIID?

    # Translation support
    i18n = TranslationField(fields=("name",))

    name = models.CharField(max_length=100, verbose_name=_("Name"))
    name_i18n: str  # for typing

    # Classification
    place_type = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        related_name="places",
    )

    # Location
    location = models.PointField(srid=4326, spatial_index=True)
    elevation = models.IntegerField(null=True, blank=True)
    country_code = CountryField(db_index=True)

    parent = models.ForeignKey(
        "self",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="children",
    )

    importance = models.SmallIntegerField(
        default=25,
        db_index=True,
        verbose_name=_("Importance"),
        help_text=_("Higher values = more important (0-100 scale)"),
    )

    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    is_public = models.BooleanField(default=False, db_index=True)
    is_modified = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Modifed"),
        help_text=_("Any modification compared to the original source were done"),
    )

    # External source references (many-to-many through association)
    source_set = models.ManyToManyField(
        Organization,
        through="GeoPlaceSourceAssociation",
        verbose_name=_("Sources"),
        related_name="geo_places",
    )

    image_set = models.ManyToManyField(
        Image,
        through="GeoPlaceImageAssociation",
        related_name="geo_places",
        verbose_name=_("Images"),
    )

    class Meta:
        verbose_name = _("Geo Place")
        verbose_name_plural = _("Geo Places")
        ordering = ("-importance", Lower("name_i18n"))
        indexes = [
            models.Index(
                fields=["is_active", "is_public"], name="geoplaces_active_public_idx"
            ),
            models.Index(fields=["-importance"]),
            GinIndex(fields=["i18n"]),
            GinIndex(
                fields=["name"],
                name="geoplaces_name_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
            GistIndex(fields=["location"], name="geoplaces_location_gist_idx"),
        ]
        constraints = (
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_country_valid",
                condition=models.Q(country_code__in=settings.COUNTRIES_ONLY),
            ),
        )

    def __str__(self) -> str:
        return f"{self.name_i18n} ({self.place_type.slug})"
