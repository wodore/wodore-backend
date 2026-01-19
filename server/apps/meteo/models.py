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
        org_slug = self.source_organization.slug
        return f"{org_slug}:{self.code} ({self.slug}) - {self.description_day}"

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
        """Generate base slug from WMO code with friendly names for all 100 codes"""
        # Complete WMO 4677 code mapping (0-99)
        # Includes forecast codes (0-3, 45-99) and observational codes (4-44)
        wmo_slug_map = {
            # Clear/Cloudy (0-3)
            0: "clear",
            1: "mostly-clear",
            2: "partly-cloudy",
            3: "cloudy",
            # Observational: Atmospheric phenomena (4-19)
            4: "smoke",
            5: "haze",
            6: "dust-some",
            7: "dust",
            8: "dust-whirls",
            9: "duststorm",
            10: "mist",
            11: "fog-patches",
            12: "fog-shallow",
            13: "lightning-distant",
            14: "drizzle-distant",
            15: "rain-distant",
            16: "rain-within-sight",
            17: "thunder-distant",
            18: "squalls",
            19: "funnel-clouds",
            # Observational: Recent weather (20-29)
            20: "drizzle-recent",
            21: "rain-light-recent",
            22: "snow-light-recent",
            23: "sleet-recent",
            24: "rain-freezing-recent",
            25: "rain-recent",
            26: "snow-recent",
            27: "hail-recent",
            28: "fog-recent",
            29: "thunderstorm-recent",
            # Observational: Duststorms/sandstorms (30-39)
            30: "duststorm-slight-receding",
            31: "duststorm-slight-ongoing",
            32: "duststorm-building",
            33: "duststorm-receding",
            34: "duststorm-ongoing",
            35: "duststorm-severe",
            36: "snow-drifting-slight",
            37: "snow-drifting-heavy",
            38: "snow-blowing-slight",
            39: "snow-blowing-heavy",
            # Observational: Fog states (40-44)
            40: "fog-distant",
            41: "fog-patches-sky-visible",
            42: "fog-low-receding",
            43: "fog-receding",
            44: "fog-low-ongoing",
            # Forecast: Fog (45-49)
            45: "fog",
            46: "fog-low-building",
            47: "fog-building",
            48: "fog-rime",
            49: "fog-freezing",
            # Forecast: Drizzle (50-59)
            50: "drizzle-light-intermittent",
            51: "drizzle-light",
            52: "drizzle-intermittent",
            53: "drizzle",
            54: "drizzle-dense-intermittent",
            55: "drizzle-dense",
            56: "drizzle-freezing-light",
            57: "drizzle-freezing",
            58: "drizzle-rain-light",
            59: "drizzle-rain",
            # Forecast: Rain (60-69)
            60: "rain-light-intermittent",
            61: "rain-light",
            62: "rain-intermittent",
            63: "rain",
            64: "rain-heavy-intermittent",
            65: "rain-heavy",
            66: "rain-freezing-light",
            67: "rain-freezing",
            68: "rain-snow-light",
            69: "sleet",
            # Forecast: Snow (70-79)
            70: "snow-light-intermittent",
            71: "snow-light",
            72: "snow-intermittent",
            73: "snow",
            74: "snow-heavy-intermittent",
            75: "snow-heavy",
            76: "snow-diamond-dust",
            77: "snow-grains",
            78: "snow-crystals",
            79: "ice-pellets",
            # Forecast: Showers (80-90)
            80: "showers-rain-light",
            81: "showers-rain",
            82: "showers-rain-violent",
            83: "showers-sleet-light",
            84: "showers-sleet",
            85: "showers-snow-light",
            86: "showers-snow",
            87: "showers-snow-pellets-light",
            88: "showers-snow-pellets",
            89: "showers-hail-light",
            90: "showers-hail",
            # Forecast: Post-thunderstorm (91-94)
            91: "rain-light-post-thunderstorm",
            92: "rain-post-thunderstorm",
            93: "snow-light-post-thunderstorm",
            94: "snow-post-thunderstorm",
            # Forecast: Thunderstorm (95-99)
            95: "thunderstorm",
            96: "thunderstorm-hail-light",
            97: "thunderstorm-heavy",
            98: "thunderstorm-dust",
            99: "thunderstorm-hail-heavy",
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
