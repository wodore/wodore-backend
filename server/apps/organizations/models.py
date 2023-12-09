from django.db import models
from functools import lru_cache

from django.utils.translation import gettext_lazy as _

# from django_jsonform.models.fields import JSONField
from django.utils import timezone
from colorfield.fields import ColorField
from typing import Optional
from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

# from ..djjmt.fields import TranslationJSONField


# Create your models here.
class Organization(TimeStampedModel):
    """
    External organizations, like SAC.
    """

    i18n = TranslationField(fields=("name", "fullname", "description", "attribution", "url"))
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=100, default="", blank=True, null=True, help_text="Shortname")
    fullname = models.CharField(max_length=100, default="", blank=True, null=True, help_text="Fullname")
    description = models.TextField(default="", blank=True, null=True, help_text="Fullname")
    url = models.URLField(blank=True, max_length=300, null=True, help_text="Main url")
    attribution = models.CharField(max_length=400, default="", blank=True, null=True, help_text="Attribution text")
    link_hut_pattern = models.CharField(
        blank=True,
        max_length=300,
        help_text="Link to specific entry. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.",
    )
    logo = models.ImageField(
        max_length=300,
        upload_to="organizations/logos",
        default="organizations/logos/missing.png",
        help_text="Ref logo as image",
    )
    color_light = ColorField(help_text="light theme color as hex number with #", default="#4B8E43")
    color_dark = ColorField(help_text="dark theme color as hex number with #", default="#61B958")
    config = models.JSONField(default=dict, blank=True, help_text="Configuration dictonary")
    props_schema = models.JSONField(default=dict, blank=True, help_text="Property schema")
    order = models.PositiveSmallIntegerField(unique=True, default=0)

    @classmethod
    @lru_cache(50)
    def get_by_slug(cls, slug):
        return cls.objects.get(slug=slug)

    @classmethod
    def get_fields_all(cls):
        return [f.get_attname() for f in cls._meta.fields]

    @classmethod
    def get_fields_in(cls):
        return list(set(cls.get_fields_all()) - set(["created", "modified", "id", "order"]))

    @classmethod
    def get_fields_update(cls):
        return list(set(cls.get_fields_all()) - set(["created", "modified"]))

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
        else:
            return highest_order.get("order", 0) + 1

    class Meta(object):
        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")
        ordering = ["order"]

    def save(self, *args, **kwargs):
        if self.order == 0 or self.order is None:
            self.order = Organization.get_next_order_number()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name_i18n
