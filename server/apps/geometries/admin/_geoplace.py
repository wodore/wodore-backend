from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..models import GeoPlace


@admin.register(GeoPlace)
class GeoPlaceAdmin(ModelAdmin):
    """
    Admin interface for GeoPlace model.

    Provides management of curated geographic places imported from
    GeoNames and other sources.
    """

    form = required_i18n_fields_form_factory("name")

    list_display = (
        "name",
        "place_type_display",
        "country_code",
        "elevation_display",
        "importance",
        "is_public",
        "is_active",
        "is_modified",
    )

    list_display_links = ("name",)

    list_filter = (
        "is_public",
        "is_active",
        "is_modified",
        "place_type__parent",  # Filter by category parent (e.g., terrain, transport)
        "place_type",
        "country_code",
    )

    search_fields = ("name", "name_i18n")

    autocomplete_fields = ("place_type", "parent")

    readonly_fields = (
        "name_i18n",
        "location_display",
        "created",
        "modified",
    )

    fieldsets = (
        (_("Identification"), {"fields": ("name", "name_i18n", "place_type")}),
        (
            _("Location"),
            {
                "fields": (
                    "location",
                    "location_display",
                    "elevation",
                    "country_code",
                    "parent",
                )
            },
        ),
        (
            _("Status"),
            {"fields": ("is_active", "is_public", "is_modified", "importance")},
        ),
        (_("Metadata"), {"classes": ["collapse"], "fields": ("created", "modified")}),
    )

    list_per_page = 50

    # Display methods

    @display(description=_("Type"))
    def place_type_display(self, obj: GeoPlace) -> str:
        """Display place type with parent if exists."""
        if obj.place_type.parent:
            return f"{obj.place_type.parent.name_i18n} → {obj.place_type.name_i18n}"
        return obj.place_type.name_i18n

    @display(description=_("Elevation"))
    def elevation_display(self, obj: GeoPlace) -> str:
        """Display elevation with unit."""
        if obj.elevation is not None:
            return f"{obj.elevation} m"
        return "-"

    @display(description=_("Location"))
    def location_display(self, obj: GeoPlace) -> str:
        """Display location coordinates."""
        if obj.location:
            return format_html(
                '<a href="https://www.google.com/maps?q={},{}" target="_blank">{:.6f}, {:.6f}</a>',
                obj.location.y,
                obj.location.x,
                obj.location.y,
                obj.location.x,
            )
        return "-"
