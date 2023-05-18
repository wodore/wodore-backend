#from django.db import models
from django.db.models import Model, DateTimeField, CharField, TextField, SlugField, URLField, JSONField, BooleanField, ImageField, PositiveSmallIntegerField
from django.utils import timezone
from colorfield.fields import ColorField
from typing import Optional
from model_utils.models import TimeStampedModel


# Create your models here.
class Organization(TimeStampedModel):
    """
    External organizations, like SAC.
    """
    slug = SlugField(unique=True)
    is_active = BooleanField(default=True, db_index=True)
    name = CharField(max_length=100)
    fullname = CharField(max_length=100, help_text="Long name of reference")
    description = TextField(blank=True)
    url = URLField(max_length=300, help_text="Main url")
    attribution = CharField(blank=True, max_length=400, help_text="Attribution text")
    link_hut_pattern = CharField(blank=True, max_length=300, help_text="Link to specific entry. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.")
    logo = ImageField(max_length=40, upload_to="huts/orgianizations/logos", help_text="Ref logo as image")
    color_light = ColorField(help_text="light theme color as hex number with #", default="#4B8E43")
    color_dark = ColorField(help_text="dark theme color as hex number with #", default="#61B958")
    config = JSONField(default=dict, blank=True, help_text="Configuration dictonary")
    props_schema = JSONField(default=dict, blank=True, help_text="Property schema")
    order = PositiveSmallIntegerField(unique=True)

    class Meta(object):
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
        ordering = (['order'])


    def __str__(self) -> str:
        return self.slug
