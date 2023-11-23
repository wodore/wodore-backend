from django.utils.html import mark_safe
from jsoneditor.forms import JSONEditor
from modeltrans.admin import ActiveLanguageMixin
from unfold.decorators import display

# Models
from django.db import models

from .views import OrganizationDetailView

# Register your models here.

from .models import Organization
from ..djjmt.utils import override, django_get_normalised_language, activate

from ..admin.admin import ModelAdmin

from django.contrib import admin

# try:
#    from unfold.admin import ModelAdmin
# except ModuleNotFoundError:
#    from django.contrib.admin import ModelAdmin

from unfold.widgets import UnfoldAdminColorInputWidget

from django.urls import path, reverse
from django.utils.html import format_html


@admin.register(Organization)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class OrganizationAdmin(ModelAdmin[Organization]):
    """Admin panel example for ``BlogPost`` model."""

    view_on_site = True
    list_display = ["organization", "url_link", "light", "dark", "detail"]
    list_display_links = ["organization"]
    search_fields = ["slug", "name", "fullname"]
    readonly_fields = ["created", "modified"]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        activate(django_get_normalised_language())
        with override(django_get_normalised_language()):
            # Change title
            extra_context["original"] = self.model.objects.get(pk=object_id).name
            extra_context["subtitle"] = self.model.objects.get(pk=object_id).name
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        return [
            path(
                "<pk>/detail",
                self.admin_site.admin_view(OrganizationDetailView.as_view()),
                name=f"organizations_organization_detail",
            ),
            *super().get_urls(),
        ]

    @display(description="")
    def detail(self, obj: Organization) -> str:
        url = reverse("admin:organizations_organization_detail", args=[obj.pk])
        view = (
            f'<span><a class="text-sm" href="{url}"> <span class="material-symbols-outlined"> visibility </span> </a>'
        )
        url = reverse("admin:organizations_organization_change", args=[obj.pk])
        edit = f'<a class="text-sm" href="{url}"> <span class="material-symbols-outlined"> edit </span> </a><span>'
        return format_html(view + edit)

    @display(header=True)
    def organization(self, obj):
        """
        Third argument is short text which will appear as prefix in circle
        """
        activate(django_get_normalised_language())
        return (obj.name, obj.fullname, self.logo_thumb(obj))
        with override(django_get_normalised_language()):
            return (obj.name, obj.fullname, self.logo_thumb(obj))

    def show_color(self, value, width=32, height=16, radius=4):
        return mark_safe(
            f'<div style="background-color:{value};border-radius:{radius}px;min-height:{height}px;min-width:{width}px;max-height:{height}px;max-width:{width}px"></div>'
        )

    def light(self, obj):
        return self.show_color(obj.color_light)

    def dark(self, obj):
        return self.show_color(obj.color_dark)

    @display(description="Description")
    def description_t(self, obj):
        with override(django_get_normalised_language()):
            return obj.description

    @display(description="URL", header=True)
    def url_link(self, obj):
        icon = '<span class="material-symbols-outlined" style="font-size:x-small">open_in_new</span>'
        return mark_safe(f'<a class="text-sm" target="_blank" href="{obj.url}"/>{obj.url} {icon}</a>'), mark_safe(
            f'<span class="text-xs">{obj.link_hut_pattern}</span>'
        )

    def logo_thumb(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "20"/>')

    def logo_preview(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "50"/>')
