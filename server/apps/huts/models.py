#from django.db import models
from django.db.models import Model, DateTimeField, CharField, TextField, SlugField, URLField, JSONField, BooleanField, ImageField
from colorfield.fields import ColorField
from typing import Optional


# Create your models here.
class Organization(Model):
    """
    This model is used just as an example.

    With it we show how one can:
    - Use fixtures and factories
    - Use migrations testing

    """
    slug = SlugField(primary_key=True)
    is_active = BooleanField(default=True, db_index=True)
    name = CharField(max_length=100)
    fullname = CharField(max_length=100, help_text="Long name of reference")
    description = TextField(blank=True)
    url = URLField(max_length=300, help_text="Main url")
    attribution = CharField(blank=True, max_length=400, help_text="Attribution text")
    link_hut_pattern = CharField(blank=True, max_length=300, help_text="Link to specific entry. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.")
    logo = ImageField(max_length=40, upload_to="orgianization/logos", help_text="Ref logo as image")
    #icon = CharField(max_length=40, help_text="Ref icon as mdi-<name>")
    color_light = ColorField(help_text="light theme color as hex number with #", default="#4B8E43")
    color_dark = ColorField(help_text="dark theme color as hex number with #", default="#61B958")
    config = JSONField(default=dict, blank=True, help_text="Configuration dictonary")
    props_schema = JSONField(default=dict, blank=True, help_text="Property schema")
    created = DateTimeField(auto_now_add=True)
    updated = DateTimeField(auto_now=True)

    class Meta(object):
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'

    def __str__(self) -> str:
        return self.slug


#class Reference(SQLModel):
#    #slug:           str           = Field(unique=True, primary_key=True, index=True,
#    #                                      max_length=30, schema_extra={"example": "sac"})
#    #name:           str           = Field(..., description="Short name of reference",
#    #                                            schema_extra = {"example": "SAC"})
#    #fullname:       str           = Field(..., description="Long name of reference",
#    #                                            schema_extra = {"example": "Schweizer Alpen Club"})
#    #url:            str = Field(..., description="Main url", schema_extra = {"example": "https://sac.ch"})
#    #link_pattern:   Optional[str] = Field(..., description="Link to specific entry. Variables to use: {{id}}, {{lang}}, {{props}}, {{config}}.", 
#    #                                            schema_extra = {"example": "https://sac.ch/hut/{{id}}?l={{lang}}"})
#    #attribution:    str           = Field("", description="Attribution text",
#    #                                            schema_extra = {"example": "(c) SAC"})
#    #logo:           str           = Field("", max_length=40, description="Ref logo as image",
#    #                                            schema_extra = {"example": "sac.png"})
#    #icon:           str           = Field("", max_length=40, description="Ref icon as mdi-<name>",
#    #                                            schema_extra = {"example": "mdi-eye"})
#    #color_light:    str           = Field("", max_length=7, description="light theme color as hex number with #",
#    #                                            schema_extra = {"example": "fe54d2"})
#    #color_dark:    str           = Field("", max_length=7, description="dark theme color as hex number with #",
#    #                                            schema_extra = {"example": "1ef432"})
#    #config:         dict          = Field(default_factory=dict, sa_column=Column(JSON))
#
#    #is_active:      bool          = Field(default=True, index=True)
#    #props_schema:   dict          = Field(default_factory=dict, sa_column=Column(JSON))
# 

    #description:    Optional[str]
    #is_active:      bool          = Field(default=True, index=True)
    #props_schema:   dict          = Field(default_factory=dict, sa_column=Column(JSON))
    #huts: List["HutRefLink"] = Relationship(back_populates="ref_link", sa_relationship_kwargs={"lazy": "raise"}) # does not work if in ExternBase

