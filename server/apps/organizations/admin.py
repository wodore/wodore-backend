from django.contrib import admin

# Models
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

# try:
#    from unfold.admin import ModelAdmin
# except ModuleNotFoundError:
#    from django.contrib.admin import ModelAdmin
from .forms import OrganizationAdminFieldsets

# Register your models here.
from .models import Organization
from .views import OrganizationDetailView


@admin.register(Organization)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class OrganizationAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    form = required_i18n_fields_form_factory("name", "fullname")
    fieldsets = OrganizationAdminFieldsets
    view_on_site = True
    list_display = ("organization", "url_link", "light", "dark", "order_small", "detail")
    list_display_links = ("organization",)
    search_fields = ("slug", "name_i18n", "fullname_i18n")
    readonly_fields = (
        "name_i18n",
        "fullname_i18n",
        "description_i18n",
        "url_i18n",
        "attribution_i18n",
        "created",
        "modified",
    )

    # formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}

    def get_urls(self):
        return [
            path(
                "<pk>/detail",
                self.admin_site.admin_view(OrganizationDetailView.as_view()),
                name="organizations_organization_detail",
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
        return (obj.name_i18n, obj.fullname_i18n, self.logo_thumb(obj))

    @display(description="#", ordering=None)
    def order_small(self, obj):
        return mark_safe(f"<small>{obj.order}</small>")

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
        return obj.description_i18n

    @display(description="URL", header=True)
    def url_link(self, obj):
        icon = '<span class="material-symbols-outlined" style="font-size:x-small">open_in_new</span>'
        return mark_safe(
            f'<a class="text-sm" target="_blank" href="{obj.url_i18n}"/>{obj.url_i18n} {icon}</a>'
        ), mark_safe(f'<span class="text-xs">{obj.link_hut_pattern}</span>')

    def logo_thumb(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "20"/>')

    def logo_preview(self, obj):  # new
        return mark_safe(f'<img src = "{obj.logo.url}" width = "50"/>')
