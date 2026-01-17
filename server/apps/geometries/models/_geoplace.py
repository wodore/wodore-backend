from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from ._associations import GeoPlaceSourceAssociation


class GeoPlace(TimeStampedModel):
    """
    Canonical, curated geographic place.
    Can aggregate data from multiple sources (GeoNames, OSM, manual edits).
    """

    # TODO: add index which starts at 10000 or UIID?

    # Translation support
    i18n = TranslationField(fields=("name",))

    name = models.CharField(max_length=200, verbose_name=_("Name"))
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
            # Composite index for active + public + importance (used in search/nearby)
            models.Index(
                fields=["is_active", "is_public", "importance"],
                name="geoplaces_act_pub_imp_idx",
            ),
            # Composite index for active + public + country (used in search)
            models.Index(
                fields=["is_active", "is_public", "country_code"],
                name="geoplaces_act_pub_cnt_idx",
            ),
            models.Index(fields=["-importance"]),
            # GIN index for trigram similarity search (critical for search performance)
            GinIndex(
                fields=["name"],
                name="geoplaces_name_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
            # GIN index for i18n fields (supports multi-language search)
            GinIndex(fields=["i18n"]),
            # GIST index for spatial queries (critical for nearby search)
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

    @classmethod
    def create_with_source(
        cls,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
    ) -> "GeoPlace":
        """
        Create a new GeoPlace and associate it with a source.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source (e.g., GeoNames ID)
            **kwargs: Fields for GeoPlace creation (name, location, etc.)

        Returns:
            Created GeoPlace instance with source association

        Example:
            place = GeoPlace.create_with_source(
                source="geonames",
                source_id="2658434",
                name="Matterhorn",
                location=Point(7.6588, 45.9763),
                place_type=peak_category,
                elevation=4478,
                country_code="CH",
                importance=95,
            )
        """
        from ._associations import GeoPlaceSourceAssociation

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create the place
        place = cls.objects.create(**kwargs)

        # Create source association
        GeoPlaceSourceAssociation.objects.create(
            geo_place=place,
            organization=source_obj,
            source_id=source_id or "",
        )

        return place

    def add_source(
        self,
        source: Organization | int | str,
        source_id: str | None = None,
        **kwargs,
    ) -> GeoPlaceSourceAssociation:
        """
        Add or update a source association for this GeoPlace.

        Args:
            source: Organization instance, ID, or slug
            source_id: External ID used by the source
            **kwargs: Additional fields for the association (confidence, source_props, etc.)

        Returns:
            Created or updated GeoPlaceSourceAssociation instance

        Example:
            place.add_source("geonames", source_id="2658434", confidence=1.0)
        """
        from ._associations import GeoPlaceSourceAssociation

        # Resolve source to Organization instance
        if isinstance(source, str):
            source_obj = Organization.objects.get(slug=source)
        elif isinstance(source, int):
            source_obj = Organization.objects.get(pk=source)
        else:
            source_obj = source

        # Create or update association
        association, _ = GeoPlaceSourceAssociation.objects.update_or_create(
            geo_place=self,
            organization=source_obj,
            defaults={
                "source_id": source_id or "",
                **kwargs,
            },
        )

        return association
