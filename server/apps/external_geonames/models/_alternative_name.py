from django.db import models
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseManager


class AlternativeName(models.Model):
    """
    Alternative names for GeoNames places in different languages.

    Stores multilingual alternate names, historical names, colloquial names,
    abbreviations, and postal codes from GeoNames alternate names data.
    """

    objects: BaseManager = BaseManager()

    # Primary identifier
    alternatename_id = models.BigIntegerField(
        primary_key=True,
        verbose_name=_("Alternate Name ID"),
        help_text=_("Unique GeoNames alternate name identifier"),
    )

    # Foreign key to GeoName
    geoname = models.ForeignKey(
        "external_geonames.GeoName",
        on_delete=models.CASCADE,
        related_name="alternative_names",
        verbose_name=_("GeoName"),
        help_text=_("GeoNames place this name refers to"),
        db_index=True,
    )

    # Language and name
    iso_language = models.CharField(
        max_length=7,
        verbose_name=_("ISO Language"),
        help_text=_(
            "ISO 639 language code (2-3 chars) optionally followed by country code "
            "(e.g., 'zh-CN') or variant (e.g., 'zh-Hant'). Special codes: 'post' for "
            "postal codes, 'iata'/'icao'/'faac' for airport codes, 'fr_1793' for French "
            "Revolution names, 'abbr' for abbreviations, 'link' for website links, "
            "'wkdt' for Wikidata IDs"
        ),
        db_index=True,
    )
    alternate_name = models.CharField(
        max_length=400,
        verbose_name=_("Alternate Name"),
        help_text=_("Alternate name or name variant"),
        db_index=True,
    )

    # Name attributes (stored as boolean for database efficiency)
    is_preferred_name = models.BooleanField(
        default=False,
        verbose_name=_("Is Preferred Name"),
        help_text=_("True if this is an official/preferred name"),
        db_index=True,
    )
    is_short_name = models.BooleanField(
        default=False,
        verbose_name=_("Is Short Name"),
        help_text=_(
            "True if this is a short name (e.g., 'California' for 'State of California')"
        ),
    )
    is_colloquial = models.BooleanField(
        default=False,
        verbose_name=_("Is Colloquial"),
        help_text=_(
            "True if this is a colloquial or slang term (e.g., 'Big Apple' for 'New York')"
        ),
    )
    is_historic = models.BooleanField(
        default=False,
        verbose_name=_("Is Historic"),
        help_text=_(
            "True if this is a historic name used in the past (e.g., 'Bombay' for 'Mumbai')"
        ),
    )

    # Time period (for historic names)
    from_period = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("From Period"),
        help_text=_("Period when the name started being used"),
    )
    to_period = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name=_("To Period"),
        help_text=_("Period when the name stopped being used"),
    )

    class Meta:
        verbose_name = _("Alternative Name")
        verbose_name_plural = _("Alternative Names")
        ordering = ("geoname_id", "iso_language", "alternate_name")
        indexes = [
            models.Index(fields=["geoname", "iso_language"]),
            models.Index(fields=["iso_language", "alternate_name"]),
            models.Index(fields=["is_preferred_name"]),
            models.Index(fields=["geoname", "is_preferred_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.alternate_name} ({self.iso_language})"
