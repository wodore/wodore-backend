from functools import lru_cache

from colorfield.fields import ColorField

from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from django.contrib.postgres.indexes import GinIndex
from django.db import models

# from django_jsonform.models.fields import JSONField
from django.utils.translation import gettext_lazy as _

# from modeltrans.manager import MultilingualManager
from server.core.managers import BaseMutlilingualManager


class Organization(TimeStampedModel):
    """
    External organizations, like SAC.
    """

    i18n = TranslationField(fields=("name", "fullname", "description", "attribution", "url"))
    objects = BaseMutlilingualManager()

    slug = models.SlugField(unique=True, verbose_name=_("Slug"), db_index=True)
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Active"))
    name = models.CharField(max_length=100, default="", blank=True, null=True, verbose_name=_("Shortname"))
    fullname = models.CharField(max_length=100, default="", blank=True, null=True, verbose_name=_("Fullname"))
    description = models.TextField(default="", blank=True, null=True, help_text=_("Description"))
    url = models.URLField(
        blank=True, max_length=300, null=True, verbose_name=_("URL"), help_text=_("URL to organization's homepage")
    )
    attribution = models.CharField(max_length=400, default="", blank=True, null=True, verbose_name=_("Attribution"))
    link_hut_pattern = models.CharField(
        blank=True,
        max_length=300,
        verbose_name=_("Link patten to object"),
        help_text=_(
            "Link pattern to corresponding object. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.)"
        ),
    )
    logo = models.ImageField(
        max_length=300,
        upload_to="organizations/logos",
        default="organizations/logos/missing.png",
        verbose_name=_("Logo"),
        help_text=_("Organiztion logo as image"),
    )
    color_light = ColorField(
        verbose_name=_("Light Color"), help_text=_("light theme color as hex number with #"), default="#4B8E43"
    )
    color_dark = ColorField(
        verbose_name=_("Dark Color"), help_text=_("dark theme color as hex number with #"), default="#61B958"
    )
    config = models.JSONField(default=dict, blank=True, verbose_name=_("Configuration dictonary"))
    props_schema = models.JSONField(default=dict, blank=True, help_text=_("Property schema"))
    order = models.PositiveSmallIntegerField(unique=False, default=0, verbose_name=_("Order"))

    class Meta:
        verbose_name = _("Organization")
        ordering = ("order", "name_i18n")
        indexes = (GinIndex(fields=["i18n"]),)

    def __str__(self) -> str:
        return self.name_i18n

    @classmethod
    @lru_cache(50)
    def get_by_slug(cls, slug):
        return cls.objects.get(slug=slug)

    @classmethod
    def get_fields_all(cls):
        return [f.get_attname() for f in cls._meta.fields]

    @classmethod
    def get_fields_in(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified", "id", "order"})

    @classmethod
    def get_fields_update(cls):
        return list(set(cls.get_fields_all()) - {"created", "modified"})

    @classmethod
    def get_fields_out(cls):
        return cls.get_fields_all()

    @classmethod
    def get_fields_exclude(cls):
        return ["created", "modified"]

    @classmethod
    def get_next_order_number(cls):
        highest_order = Organization.objects.all().order_by("-order").values("order").first()
        if highest_order is None:
            return 0
        return highest_order.get("order", 0) + 1

    def save(self, *args, **kwargs):
        if self.order == 0 or self.order is None:
            self.order = Organization.get_next_order_number()
        super().save(*args, **kwargs)
