from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from ..models import Feature


@admin.register(Feature)
class FeatureAdmin(ModelAdmin):
    """
    Admin for GeoNames Feature configuration.

    Allows editing of is_enabled, default_place_type, importance_weight, and notes.
    Feature codes and descriptions are maintained via management command.
    """

    list_display = (
        "feature_code_display",
        "name_description_display",
        "is_enabled",
        # "default_place_type",  # TODO: Enable after geoplace app is created
        "importance",
    )
    list_display_links = ("feature_code_display", "name_description_display")
    list_filter = (
        "is_enabled",
        "feature_class",
        # "default_place_type",  # TODO: Enable after geoplace app is created
    )
    search_fields = ("feature_code", "name", "description")
    readonly_fields = ("feature_class", "feature_code", "name", "description")

    # Enable inline editing
    list_editable = ("is_enabled", "importance")

    fieldsets = (
        (
            _("Feature Information"),
            {
                "fields": (
                    ("feature_class", "feature_code"),
                    "name",
                    "description",
                )
            },
        ),
        (
            _("Import Configuration"),
            {
                "fields": (
                    "is_enabled",
                    # "default_place_type",  # TODO: Enable after geoplace app is created
                    "importance",
                )
            },
        ),
        (
            _("Notes"),
            {
                "classes": ["collapse"],
                "fields": ("notes",),
            },
        ),
    )

    @display(description=_("Feature Code"), ordering="feature_code", label=True)
    def feature_code_display(self, obj: Feature) -> str:
        return f"{obj.feature_class}.{obj.feature_code}"

    @display(header=True, description=_("Name"), ordering="name")
    def name_description_display(self, obj: Feature) -> tuple:
        return (obj.name, obj.description if obj.description else "")
