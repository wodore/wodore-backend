from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from server.core.managers import BaseMutlilingualManager


class HutType(models.Model):
    i18n = TranslationField(fields=("name", "description"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True)
    # name = TranslationJSONField(models.CharField(max_length=100), help_text="Hut type name")
    # description = TranslationJSONField(models.CharField(max_length=400), help_text="Hut type description")
    name = models.CharField(max_length=100, blank=True, null=True, default="", help_text="Hut type name")
    description = models.CharField(max_length=400, blank=True, null=True, default="", help_text="Hut type description")
    level = models.PositiveSmallIntegerField(default=0, help_text=_("Comfort level, higher is more comfort"))
    symbol = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/symbols/detailed/unknown.png",
        help_text="Normal icon",
    )
    symbol_simple = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/symbols/simple/unknown.png",
        help_text="Simple icon",
    )
    icon = models.ImageField(
        max_length=300,
        upload_to="huts_type/icons",
        default="huts/types/icons/unknown.png",
        help_text="Black icon",
    )

    def __str__(self) -> str:
        if self.name_i18n is not None:
            return self.name_i18n
        return "-"

    class Meta:
        verbose_name = _("Hut Type")
        verbose_name_plural = _("Hut Types")
        ordering = ("level", "slug")
        indexes = (GinIndex(fields=["i18n"]),)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name_i18n)
        super().save(*args, **kwargs)
