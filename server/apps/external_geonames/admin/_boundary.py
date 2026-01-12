from django.contrib import admin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _


from server.apps.manager.admin import ModelAdmin

from ..models import Boundary


@admin.register(Boundary)
class BoundaryAdmin(ModelAdmin):
    """
    Admin for GeoNames Boundaries.

    Read-only view of imported GeoNames polygon/administrative boundary data.
    Data is managed via import_geonames management command.
    """

    list_display = (
        "name",
        "feature_code",
        "country_code",
        "admin_level",
    )
    list_filter = (
        "country_code",
        "admin_level",
        "feature_code",
    )
    search_fields = ("name", "geoname_id")
    readonly_fields = (
        "geoname_id",
        "name",
        "feature_code",
        # "geometry",
        "country_code",
        "admin_level",
        "modification_date",
        "created",
        "modified",
    )

    fieldsets = (
        (
            _("Identification"),
            {
                "fields": (
                    "geoname_id",
                    "name",
                    "feature_code",
                )
            },
        ),
        (
            _("Administrative"),
            {
                "fields": (
                    "country_code",
                    "admin_level",
                )
            },
        ),
        (
            _("Geography"),
            {"fields": ("geometry",)},
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "modification_date",
                    ("created", "modified"),
                )
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable manual creation - data is imported via command."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Boundary | None = None
    ) -> bool:
        """Disable deletion - data is managed via command."""
        return False
