import contextlib

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from django.contrib import admin
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .models import WeatherCode


@admin.register(WeatherCode)
class WeatherCodeAdmin(ModelAdmin):
    """Admin panel for WeatherCode model."""

    list_display = (
        "code",
        "slug",
        "priority",
        "source_org_display",
        "symbol_preview_day",
        "symbol_preview_night",
        "description_preview",
        "category_display",
    )
    list_display_links = ("code", "slug")
    search_fields = (
        "code",
        "slug",
        "source_id",
        "description_day",
        "description_night",
    )
    list_filter = (
        "source_organization",
        "category",
        "priority",
        "code",
    )
    readonly_fields = (
        "id",
        "created",
        "modified",
        "slug",
    )
    fieldsets = (
        (
            _("Source"),
            {
                "fields": (
                    "source_organization",
                    "source_id",
                )
            },
        ),
        (
            _("WMO Code"),
            {
                "fields": (
                    "code",
                    "slug",
                    "priority",
                    "category",
                )
            },
        ),
        (
            _("Descriptions"),
            {
                "fields": (
                    "description_day",
                    "description_night",
                )
            },
        ),
        (
            _("Symbols"),
            {
                "fields": (
                    "symbol_day",
                    "symbol_night",
                )
            },
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "created",
                    "modified",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.select_related(
            "source_organization",
            "category",
            "symbol_day",
            "symbol_night",
        )

    @display(description=_("Organization"))
    def source_org_display(self, obj):
        """Display source organization."""
        if obj.source_organization:
            return obj.source_organization.name or obj.source_organization.slug
        return "-"

    @display(description=_("Category"))
    def category_display(self, obj):
        """Display category."""
        if obj.category:
            if obj.category.parent:
                return f"{obj.category.parent.slug}.{obj.category.slug}"
            return obj.category.slug
        return "-"

    @display(description=_("Day"))
    def symbol_preview_day(self, obj):
        """Show day symbol preview."""
        try:
            if obj.symbol_day and obj.symbol_day.svg_file:
                return mark_safe(
                    f'<img src="{obj.symbol_day.svg_file.url}" width="30" height="30" '
                    f'style="object-fit:contain;" title="{obj.symbol_day.slug}" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Night"))
    def symbol_preview_night(self, obj):
        """Show night symbol preview."""
        try:
            if obj.symbol_night and obj.symbol_night.svg_file:
                return mark_safe(
                    f'<img src="{obj.symbol_night.svg_file.url}" width="30" height="30" '
                    f'style="object-fit:contain;" title="{obj.symbol_night.slug}" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Description"))
    def description_preview(self, obj):
        """Show truncated description."""
        if obj.description_day:
            desc = obj.description_day
            if len(desc) > 40:
                desc = desc[:37] + "..."
            return desc
        return "-"
