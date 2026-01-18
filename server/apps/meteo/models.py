from django.db import models
from django.utils.translation import gettext_lazy as _
from modeltrans.fields import TranslationField

from server.core.models import TimeStampedModel
from server.core.managers import BaseMutlilingualManager
from server.apps.symbols.models import Symbol
from server.apps.categories.models import Category
from server.apps.organizations.models import Organization


class WeatherCode(TimeStampedModel):
    """
    WMO weather codes (WMO 4677) with localized descriptions and symbol mappings.
    Used for mapping weather API codes to human-readable descriptions and icons.
    """

    i18n = TranslationField(fields=("description_day", "description_night"))
    objects = BaseMutlilingualManager()
    code = models.PositiveSmallIntegerField(
        verbose_name=_("Weather Code"),
        help_text=_("WMO weather code (e.g., 0 = clear sky, 61 = rain)"),
        db_index=True,
    )
    slug = models.SlugField(
        max_length=100,
        verbose_name=_("Slug"),
        db_index=True,
    )
    priority = models.PositiveSmallIntegerField(
        default=50,
        verbose_name=_("Priority"),
        help_text=_(
            "Priority for WMO code mapping (higher = more important, default: 50)"
        ),
        db_index=True,
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weather_codes",
        verbose_name=_("Category"),
        help_text=_("Weather category for grouping"),
        db_index=False,
    )
    description_day = models.CharField(
        max_length=200,
        verbose_name=_("Description (Day)"),
        help_text=_("Weather description for daytime"),
    )
    description_night = models.CharField(
        max_length=200,
        verbose_name=_("Description (Night)"),
        help_text=_("Weather description for nighttime"),
    )
    symbol_day = models.ForeignKey(
        Symbol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weather_codes_day",
        verbose_name=_("Symbol (Day)"),
        help_text=_("Weather symbol for daytime"),
    )
    symbol_night = models.ForeignKey(
        Symbol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weather_codes_night",
        verbose_name=_("Symbol (Night)"),
        help_text=_("Weather symbol for nighttime"),
    )

    source_organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="weather_codes",
        verbose_name=_("Source Organization"),
        help_text=_("Organization providing the weather code mapping"),
        db_index=False,
    )
    source_id = models.CharField(
        max_length=50,
        verbose_name=_("Source ID"),
        help_text=_("Weather code ID in the source organization's system"),
    )

    class Meta:
        verbose_name = _("Weather Code")
        verbose_name_plural = _("Weather Codes")
        ordering = ("source_organization", "code", "-priority")
        indexes = [
            models.Index(fields=["source_organization", "code", "-priority"]),
            models.Index(fields=["source_organization", "slug"]),
            models.Index(fields=["code", "-priority"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_organization", "slug"],
                name="unique_source_slug",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_organization.slug}:{self.code} ({self.slug}) - {self.description_day}"

    def save(self, *args, **kwargs):
        """Auto-generate unique slug if not set, or handle conflicts on updates"""
        if not self.slug:
            # No slug set - generate one
            base_slug = self._generate_base_slug()
            self.slug = self._ensure_unique_slug(base_slug)
        elif self.pk:
            # Existing object with slug - check if slug conflicts with another record
            # This handles the case where slug was manually changed
            conflict_exists = (
                WeatherCode.objects.filter(
                    source_organization=self.source_organization, slug=self.slug
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if conflict_exists:
                # Slug conflicts - generate alternative slug
                base_slug = self.slug
                self.slug = self._ensure_unique_slug(base_slug)

        super().save(*args, **kwargs)

    def _generate_base_slug(self):
        """Generate base slug from WMO code or category"""
        # Map common WMO codes to simple slugs
        wmo_slug_map = {
            0: "sunny",
            1: "mostly-sunny",
            2: "partly-cloudy",
            3: "cloudy",
            45: "fog",
            48: "fog",
            51: "drizzle-light",
            53: "drizzle",
            55: "drizzle-heavy",
            56: "freezing-drizzle-light",
            57: "freezing-drizzle",
            61: "rain-light",
            63: "rain",
            65: "rain-heavy",
            66: "freezing-rain-light",
            67: "freezing-rain",
            71: "snow-light",
            73: "snow",
            75: "snow-heavy",
            77: "snow-grains",
            80: "rain-showers-light",
            81: "rain-showers",
            82: "rain-showers-heavy",
            85: "snow-showers-light",
            86: "snow-showers",
            95: "thunderstorm",
            96: "thunderstorm-hail-light",
            99: "thunderstorm-hail",
        }

        return wmo_slug_map.get(self.code, f"wmo-{self.code}")

    def _ensure_unique_slug(self, base_slug):
        """Ensure slug is unique within organization, add -alt1, -alt2, etc if needed"""
        slug = base_slug
        counter = 1

        while (
            WeatherCode.objects.filter(
                source_organization=self.source_organization, slug=slug
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            slug = f"{base_slug}-alt{counter}"
            counter += 1

        return slug
