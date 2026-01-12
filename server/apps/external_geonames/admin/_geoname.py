from django.contrib import admin
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display
from unfold.admin import TabularInline

from server.apps.manager.admin import ModelAdmin

from ..models import AlternativeName, GeoName


class AlternativeNameInline(TabularInline):
    """Inline admin for alternative names."""

    model = AlternativeName
    extra = 0
    can_delete = False

    fields = (
        "iso_language",
        "alternate_name",
        "is_preferred_name",
        "is_short_name",
        "is_colloquial",
        "is_historic",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ChildGeoNameInline(TabularInline):
    """Inline admin for child GeoNames."""

    model = GeoName
    fk_name = "parent"
    extra = 0
    can_delete = False

    fields = (
        "geoname_id",
        "name",
        "feature",
        "hierarchy_type",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ImportanceRangeFilter(admin.SimpleListFilter):
    """Filter GeoNames by feature importance ranges."""

    title = _("feature importance")
    parameter_name = "importance_range"

    def lookups(self, request, model_admin):
        return (
            ("high", _("High (80-100)")),
            ("medium", _("Medium (50-79)")),
            ("low", _("Low (0-49)")),
        )

    def queryset(self, request, queryset):
        if self.value() == "high":
            return queryset.filter(feature__importance__gte=80)
        elif self.value() == "medium":
            return queryset.filter(
                feature__importance__gte=50, feature__importance__lt=80
            )
        elif self.value() == "low":
            return queryset.filter(feature__importance__lt=50)
        return queryset


@admin.register(GeoName)
class GeoNameAdmin(ModelAdmin):
    """
    Admin for GeoNames data.

    Read-only view of imported GeoNames point data.
    Data is managed via import_geonames management command.
    """

    inlines = [AlternativeNameInline, ChildGeoNameInline]

    list_display = (
        "feature_display",
        "name_display",
        "country_code",
        "admin_display",
        "parent_display",
        "location_coords",
        "population",
        "feature_enabled",
        "feature_importance",
        "is_deleted",
    )
    list_display_links = ("feature_display", "name_display")
    list_filter = (
        "feature__is_enabled",
        "country_code",
        "feature__feature_class",
        ImportanceRangeFilter,
        "is_deleted",
    )
    search_fields = ("name", "ascii_name", "geoname_id")
    readonly_fields = (
        "geoname_id",
        "name",
        "ascii_name",
        "feature",
        "parent",
        "hierarchy_type",
        # "location",
        "elevation",
        "population",
        "country_code",
        "admin1_code",
        "admin2_code",
        "admin3_code",
        "admin4_code",
        "timezone",
        "modification_date",
        "is_deleted",
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
                    "ascii_name",
                )
            },
        ),
        (
            _("Classification"),
            {"fields": ("feature",)},
        ),
        (
            _("Hierarchy"),
            {
                "fields": (
                    "parent",
                    "hierarchy_type",
                )
            },
        ),
        (
            _("Location"),
            {
                "fields": (
                    "location",
                    "elevation",
                    "country_code",
                )
            },
        ),
        (
            _("Administrative Divisions"),
            {
                "classes": ["collapse"],
                "fields": (
                    "admin1_code",
                    "admin2_code",
                    "admin3_code",
                    "admin4_code",
                ),
            },
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "population",
                    "timezone",
                    "modification_date",
                    "is_deleted",
                    ("created", "modified"),
                )
            },
        ),
    )

    @display(header=True, description=_("Name"), ordering="name")
    def name_display(self, obj: GeoName) -> tuple:
        return (obj.name, obj.geoname_id)

    @display(header=True, description=_("Admin"), ordering="name")
    def admin_display(self, obj: GeoName) -> tuple:
        admin_codes = []
        if obj.admin2_code:
            admin_codes.append(obj.admin2_code)
        if obj.admin3_code:
            admin_codes.append(obj.admin3_code)
        if obj.admin4_code:
            admin_codes.append(obj.admin4_code)
        return (
            obj.admin1_code if obj.admin1_code != "00" else "-",
            "«".join(admin_codes),
        )

    @display(description=_("Feature"), ordering="feature", label=True)
    def feature_display(self, obj: GeoName) -> str:
        return mark_safe(f"<large>{obj.feature.id}</large>")

    @display(header=True, description=_("Parent"), ordering="parent__name")
    def parent_display(self, obj: GeoName) -> tuple:
        if obj.parent:
            return (obj.hierarchy_type, obj.parent.name)
        return ("", "")

    @display(header=True, description=_("Location"))
    def location_coords(self, obj):
        return (
            f"{obj.location.y:.3f}/{obj.location.x:.3f}",
            f"{obj.elevation}m" if obj.elevation else "-",
        )

    @display(description=_("Enabled"), ordering="feature__is_enabled", boolean=True)
    def feature_enabled(self, obj: GeoName) -> bool:
        return obj.feature.is_enabled

    @display(description=_("Importance"), ordering="feature__importance")
    def feature_importance(self, obj: GeoName) -> int:
        return obj.feature.importance

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable manual creation - data is imported via command."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: GeoName | None = None
    ) -> bool:
        """Disable deletion - data is managed via command."""
        return False
