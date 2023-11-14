from django.contrib import admin
from django.utils.html import mark_safe
from jsoneditor.forms import JSONEditor
from modeltrans.admin import ActiveLanguageMixin

# Models
from django.db import models

# Register your models here.

from .models import Organization
from ..djjmt.utils import override, activate


@admin.register(Organization)
#class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class OrganizationAdmin(admin.ModelAdmin[Organization]):
    """Admin panel example for ``BlogPost`` model."""
    list_display = ["slug", "name_t", "name_with_url", "light", "dark", "logo_thumb"]
    list_display_links = ["slug"]
    #fields = ["__str__"]
    readonly_fields = ['logo_preview', 'created', 'modified']
    #formfield_overrides = {
    #    models.JSONField: {'widget': JSONEditor(
    #        init_options={"mode": "tree", "modes": ["tree", "code", "view"], "statusBar" : False, "navigationBar": False},
    #    )},
    #}

    def show_color(self, value, width=32, height=16):
        return mark_safe(f'<div style="background-color:{value};border-radius:4px;min-height:{height}px;min-width:{width}px;max-height:{height}px;max-width:{width}px"></div>')

    def light(self, obj):
        return self.show_color(obj.color_light)
    def dark(self, obj):
        return self.show_color(obj.color_dark)

    def name_t(self, obj):
        with override():
            return obj.name
    name_t.short_description = "Short Name"

    def name_with_url(self, obj):
        with override():
            return mark_safe(f'<a target="_blank" href="{obj.url}"/>{obj.fullname}</a>')

    def logo_thumb(self, obj): #new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "20"/>')
    logo_thumb.short_description = 'Logo'
    def logo_preview(self, obj): #new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "50"/>')