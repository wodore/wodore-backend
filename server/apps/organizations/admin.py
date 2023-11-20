from django.utils.html import mark_safe
from jsoneditor.forms import JSONEditor
from modeltrans.admin import ActiveLanguageMixin

# Models
from django.db import models

# Register your models here.

from .models import Organization
from ..djjmt.utils import override, django_get_normalised_language

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin
except ModuleNotFoundError:
    from django.contrib.admin import ModelAdmin

from unfold.widgets import UnfoldAdminColorInputWidget


@admin.register(Organization)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class OrganizationAdmin(ModelAdmin[Organization]):
    """Admin panel example for ``BlogPost`` model."""

    view_on_site = True
    list_display = ["slug", "name_with_url", "description_t", "light", "dark", "logo_thumb"]
    # list_editable = ["slug", "light"]
    list_display_links = ["slug"]
    search_fields = ["slug", "name"]
    # fields = ["__str__"]
    readonly_fields = ["logo_preview", "created", "modified"]
    # formfield_overrides = {
    #    models.JSONField: {'widget': JSONEditor(
    #        init_options={"mode": "tree", "modes": ["tree", "code", "view"], "statusBar" : False, "navigationBar": False},
    #    )},
    # }

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        for key in form.base_fields:
            if "color" in key:
                form.base_fields[key].widget = UnfoldAdminColorInputWidget()
        return form

    def show_color(self, value, width=32, height=16):
        return mark_safe(
            f'<div style="background-color:{value};border-radius:4px;min-height:{height}px;min-width:{width}px;max-height:{height}px;max-width:{width}px"></div>'
        )

    def light(self, obj):
        return self.show_color(obj.color_light)

    def dark(self, obj):
        return self.show_color(obj.color_dark)

    def name_t(self, obj):
        with override(django_get_normalised_language()):
            return obj.name

    name_t.short_description = "Short Name"

    def description_t(self, obj):
        with override(django_get_normalised_language()):
            return obj.description

    description_t.short_description = "Descrption"

    def name_with_url(self, obj):
        with override(django_get_normalised_language()):
            return mark_safe(f'<a target="_blank" href="{obj.url}"/>{obj.fullname}</a>')

    name_with_url.short_description = "Name"

    def logo_thumb(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "20"/>')

    logo_thumb.short_description = "Logo"

    def logo_preview(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "50"/>')
