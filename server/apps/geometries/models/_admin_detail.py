from __future__ import annotations

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from ._base_detail import GeoPlaceDetailBase


class AdminDetail(GeoPlaceDetailBase):
    """
    Detailed information for administrative places.

    Covers cities, villages, valleys, municipalities, and other
    administrative boundaries.
    """

    # Fields to track for modification
    _trackable_fields = [
        "admin_level",
        "population",
        "postal_code",
        "iso_code",
    ]

    # OneToOne relationship to GeoPlace
    geo_place = models.OneToOneField(
        "GeoPlace",
        on_delete=models.CASCADE,
        related_name="admin_detail",
        db_index=True,
        verbose_name=_("Geo Place"),
    )

    # OSM admin level (2 = country, 4 = state, 6 = county, 8 = city, 10 = village)
    admin_level = models.SmallIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Admin Level"),
        help_text=_(
            "OSM administrative level (2=country, 4=state, 6=county, "
            "8=city/municipality, 10=village/hamlet). Can be calculated from parent "
            "relationship but stored here for performance and OSM data preservation."
        ),
    )

    # Population
    population = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Population"),
        help_text=_("Number of inhabitants"),
    )

    # Postal code
    postal_code = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name=_("Postal Code"),
        help_text=_("Postal code for this administrative area"),
    )

    # ISO code (for regions/states)
    iso_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name=_("ISO Code"),
        help_text=_(
            "ISO 3166-2 code for administrative divisions (e.g., CH-ZH for Zürich)"
        ),
    )

    class Meta:
        verbose_name = _("Admin Detail")
        verbose_name_plural = _("Admin Details")
        indexes = [
            models.Index(fields=["admin_level"]),
            models.Index(fields=["population"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_admin_level_valid",
                condition=models.Q(admin_level__isnull=True)
                | models.Q(admin_level__gte=2) & models.Q(admin_level__lte=10),
            ),
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_population_positive",
                condition=models.Q(population__isnull=True)
                | models.Q(population__gte=0),
            ),
        ]

    def __str__(self) -> str:
        return f"Admin detail for {self.geo_place.name_i18n}"

    def calculate_admin_level(self) -> int | None:
        """
        Calculate admin level based on parent relationships.

        This is a fallback method when admin_level is not directly available.
        The hierarchy is:
        - 2: Country (no parent)
        - 4: State/Province/Canton (parent is country)
        - 6: County/District (parent is state)
        - 8: City/Municipality (parent is county)
        - 10: Village/Hamlet (parent is city)

        Returns:
            Calculated admin level or None if hierarchy cannot be determined
        """

        place = self.geo_place

        # Count parent hierarchy
        level = None
        current = place
        depth = 0

        while current.parent is not None and depth < 10:
            current = current.parent
            depth += 1

            # If we find a place with known admin_level, use it as reference
            if hasattr(current, "admin_detail") and current.admin_detail:
                if current.admin_detail.admin_level:
                    # This place's admin_level + 1 = our level
                    level = current.admin_detail.admin_level + 1
                    break

        # Fallback: estimate from depth (country=0, state=1, etc.)
        if level is None:
            level_mapping = {
                0: 2,  # Country (no parent)
                1: 4,  # State
                2: 6,  # County
                3: 8,  # City
                4: 10,  # Village
            }
            level = level_mapping.get(depth)

        return level
