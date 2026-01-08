from django.contrib import admin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _


from server.apps.manager.admin import ModelAdmin

from ..models import AlternativeName


@admin.register(AlternativeName)
class AlternativeNameAdmin(ModelAdmin):
    """
    Admin for GeoNames Alternative Names.

    Read-only view of imported GeoNames alternate names.
    Data is managed via import_geonames management command.
    """

    list_display = (
        "alternate_name",
        "iso_language",
        "geoname",
        "is_preferred_name",
        "is_historic",
    )
    list_filter = (
        "iso_language",
        "is_preferred_name",
        "is_short_name",
        "is_colloquial",
        "is_historic",
    )
    search_fields = ("alternate_name", "geoname__name", "alternatename_id")
    readonly_fields = (
        "alternatename_id",
        "geoname",
        "iso_language",
        "alternate_name",
        "is_preferred_name",
        "is_short_name",
        "is_colloquial",
        "is_historic",
        "from_period",
        "to_period",
    )

    fieldsets = (
        (
            _("Identification"),
            {
                "fields": (
                    "alternatename_id",
                    "geoname",
                )
            },
        ),
        (
            _("Name"),
            {
                "fields": (
                    "alternate_name",
                    "iso_language",
                )
            },
        ),
        (
            _("Attributes"),
            {
                "fields": (
                    "is_preferred_name",
                    "is_short_name",
                    "is_colloquial",
                    "is_historic",
                )
            },
        ),
        (
            _("Time Period"),
            {
                "classes": ["collapse"],
                "fields": (
                    "from_period",
                    "to_period",
                ),
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable manual creation - data is imported via command."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: AlternativeName | None = None
    ) -> bool:
        """Disable deletion - data is managed via command."""
        return False
