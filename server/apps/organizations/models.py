from django.db.models import (
    Model,
    DateTimeField,
    CharField,
    TextField,
    SlugField,
    URLField,
    JSONField,
    BooleanField,
    ImageField,
    PositiveSmallIntegerField,
)

from djjmt.utils import override, django_get_normalised_language

# from django_jsonform.models.fields import JSONField
from django.utils import timezone
from colorfield.fields import ColorField
from typing import Optional
from model_utils.models import TimeStampedModel
from modeltrans.fields import TranslationField

from djjmt.fields import TranslationJSONField

# from ..djjmt.fields import TranslationJSONField


# Create your models here.
class Organization(TimeStampedModel):
    """
    External organizations, like SAC.
    """

    slug = SlugField(unique=True)
    is_active = BooleanField(default=True, db_index=True)
    name = TranslationJSONField(CharField(max_length=100, default=""), help_text="Shortname")
    fullname = TranslationJSONField(CharField(max_length=100, default=""), help_text="Fullname")
    description = TranslationJSONField(TextField(default=""), help_text="Fullname")
    url = URLField(blank=True, max_length=300, help_text="Main url")
    attribution = TranslationJSONField(CharField(max_length=400, default=""), help_text="Attribution text")
    link_hut_pattern = CharField(
        blank=True,
        max_length=300,
        help_text="Link to specific entry. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.",
    )
    logo = ImageField(
        max_length=300,
        upload_to="organizations/logos",
        default="orgianizations/logos/missing.png",
        help_text="Ref logo as image",
    )
    color_light = ColorField(help_text="light theme color as hex number with #", default="#4B8E43")
    color_dark = ColorField(help_text="dark theme color as hex number with #", default="#61B958")
    config = JSONField(default=dict, blank=True, help_text="Configuration dictonary")
    props_schema = JSONField(default=dict, blank=True, help_text="Property schema")
    order = PositiveSmallIntegerField(unique=True)

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

    class Meta(object):
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
        ordering = ["order"]

    def __str__(self) -> str:
        with override(django_get_normalised_language()):
            return self.name
