from typing import ClassVar

from django import forms
from django.contrib import admin
from django.forms import ModelForm
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.manager.widgets import UnfoldReadonlyJSONSuit
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..forms import GeoPlaceAdminFieldsets
from ..models import (
    GeoPlace,
    GeoPlaceCategory,
    GeoPlaceSourceAssociation,
    GeoPlaceExternalLink,
    AmenityDetail,
)


## Custom Admin Forms


class _GeoPlaceSourceAssociationForm(ModelForm):
    """Form for GeoPlace source associations."""

    schema = forms.JSONField(
        label=_("Property JSON Schema"), required=False, widget=UnfoldReadonlyJSONSuit()
    )

    class Meta:
        model = GeoPlaceSourceAssociation
        fields = (
            "organization",
            "source_id",
            "source_props",
            "extra",
            "modified_date",
            "update_policy",
            "delete_policy",
        )

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        initial = kwargs.get("initial", {})

        if instance:
            initial = {"schema": instance.organization.props_schema}

        super().__init__(*args, **kwargs, initial=initial)


## INLINES


class GeoPlaceSourceAssociationInline(unfold_admin.TabularInline):
    """GeoPlace source association inline with editable policies."""

    form = _GeoPlaceSourceAssociationForm
    model = GeoPlaceSourceAssociation
    tab = True
    fields = (
        "organization",
        "source_id",
        "extra_display",
        "import_date",
        "modified_date",
        "update_policy",
        "delete_policy",
    )
    readonly_fields = (
        "organization",
        "source_id",
        "extra_display",
        "import_date",
        "modified_date",
    )
    extra = 0
    show_change_link = True
    verbose_name = _("Source")

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False

    @display(description=_("Extra Data"))
    def extra_display(self, obj: GeoPlaceSourceAssociation) -> str:
        """Display extra data in a readable format."""
        if not obj.extra:
            return "-"

        # Format the extra data as key-value pairs
        parts = []
        for key, value in obj.extra.items():
            if value:
                parts.append(f"{key}: {value}")

        if parts:
            return format_html(
                '<code style="font-size: 0.9em;">{}</code>', ", ".join(parts)
            )
        return "-"


class GeoPlaceExternalLinkInline(unfold_admin.TabularInline):
    """GeoPlace external link inline with ordering."""

    model = GeoPlaceExternalLink
    tab = True
    fields = (
        "external_link",
        "order",
    )
    autocomplete_fields = ("external_link",)
    extra = 1
    show_change_link = True
    verbose_name = _("External Link")

    def has_add_permission(self, request, obj):
        return True

    def has_delete_permission(self, request, obj):
        return True


def _format_categories_list(categories) -> str:
    if not categories:
        return "-"

    parts = []
    for category in categories[:3]:
        if category.parent:
            parts.append(f"{category.parent.name_i18n} → {category.name_i18n}")
        else:
            parts.append(category.name_i18n)

    if len(categories) > 3:
        parts.append(mark_safe(f"<i>+{len(categories) - 3} more ...</i>"))

    lines_html = format_html_join(mark_safe("<br>"), "{}", ((part,) for part in parts))
    return format_html(
        '<span style="font-size: 0.85em; line-height: 1.2;">{}</span>',
        lines_html,
    )


class GeoPlaceCategoryInline(unfold_admin.TabularInline):
    """GeoPlace category association inline with optional classifier."""

    model = GeoPlaceCategory
    tab = True
    fields = (
        "category",
        "classifier",
    )
    autocomplete_fields = ("category", "classifier")
    extra = 1
    show_change_link = True
    verbose_name = _("Category")

    def has_add_permission(self, request, obj):
        return True

    def has_delete_permission(self, request, obj):
        return True


## ADMIN


@admin.register(GeoPlace)
class GeoPlaceAdmin(ModelAdmin):
    """
    Admin interface for GeoPlace model.

    Provides management of curated geographic places imported from
    GeoNames and other sources.
    """

    form = required_i18n_fields_form_factory("name")
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    list_display = (
        "name",
        "slug",
        "categories_display",
        "country_code",
        "elevation_display",
        "review_status_display",
        "is_public",
        "is_active",
        "created",
        "modified",
    )

    list_display_links = ("name",)

    list_filter = (
        "review_status",
        "is_public",
        "is_active",
        "categories__parent",  # Filter by category parent (e.g., terrain, transport)
        "categories",
        "country_code",
    )

    search_fields = ("name", "name_i18n", "slug")

    autocomplete_fields = ("parent",)

    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "location_display",
        "osm_tags",
        "created",
        "modified",
    )

    sortable_by = (
        "name",
        "slug",
        "country_code",
        "elevation_display",
        "review_status",
        "is_public",
        "is_active",
        "created",
        "modified",
    )

    fieldsets = GeoPlaceAdminFieldsets

    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("categories__parent")

    def get_inlines(self, request, obj):
        """Return inlines for admin."""
        return [
            GeoPlaceCategoryInline,
            GeoPlaceSourceAssociationInline,
            GeoPlaceExternalLinkInline,
        ]

    # Display methods

    @display(description=_("Categories"))
    def categories_display(self, obj: GeoPlace) -> str:
        """Display categories with parents if available."""
        categories = list(obj.categories.all())
        return _format_categories_list(categories)

    @display(description=_("Elevation"))
    def elevation_display(self, obj: GeoPlace) -> str:
        """Display elevation with unit."""
        if obj.elevation is not None:
            return f"{obj.elevation} m"
        return "-"

    @display(description=_("Review"))
    def review_status_display(self, obj: GeoPlace) -> str:
        """Display review status with color indicator."""
        status_colors = {
            "new": "green",
            "review": "orange",
            "work": "blue",
            "done": "green",
        }
        color = status_colors.get(obj.review_status, "gray")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_review_status_display(),
        )

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


@admin.register(AmenityDetail)
class AmenityDetailAdmin(ModelAdmin):
    """
    Admin interface for AmenityDetail model.

    Provides management of amenity-specific details like opening hours,
    operating status, and brand information.
    """

    list_display = (
        "place_name",
        "place_categories",
        "operating_status",
        "brand",
        "has_opening_hours",
        "has_phones",
        "created",
        "modified",
    )

    list_display_links = ("place_name",)

    list_filter = (
        "operating_status",
        "brand__parent",
        "brand",
        "geo_place__categories__parent",
        "geo_place__categories",
        "geo_place__country_code",
    )

    search_fields = (
        "geo_place__name",
        "geo_place__name_i18n",
        "geo_place__slug",
    )

    autocomplete_fields = ("geo_place", "brand")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filter FK choices based on field type."""
        if db_field.name == "brand":
            # Only show categories that are children of 'brands' parent
            # or adjust this filter based on your category structure
            from server.apps.categories.models import Category

            # Try to get brands parent category
            brands_parent = Category.objects.filter(identifier="root.brand").first()
            if brands_parent:
                kwargs["queryset"] = Category.objects.filter(
                    parent=brands_parent
                ).order_by("name")
            else:
                # Fallback: show all categories (or implement different logic)
                kwargs["queryset"] = Category.objects.filter(
                    parent__isnull=False
                ).order_by("parent__name", "name")

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    readonly_fields = (
        "created",
        "modified",
    )

    fieldsets = [
        (
            _("Place"),
            {
                "fields": [
                    "geo_place",
                ],
            },
        ),
        (
            _("Status"),
            {
                "fields": [
                    "operating_status",
                ],
            },
        ),
        (
            _("Brand"),
            {
                "fields": [
                    "brand",
                ],
            },
        ),
        (
            _("Opening Information"),
            {
                "fields": [
                    "opening_months",
                    "opening_hours",
                ],
            },
        ),
        (
            _("Contact"),
            {
                "fields": [
                    "phones",
                ],
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": [
                    ("created", "modified"),
                ],
            },
        ),
    ]

    list_per_page = 50

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("geo_place")
            .prefetch_related("geo_place__categories__parent")
        )

    # Display methods

    @display(description=_("Place Name"))
    def place_name(self, obj: AmenityDetail) -> str:
        """Display associated place name."""
        return obj.geo_place.name_i18n

    @display(description=_("Categories"))
    def place_categories(self, obj: AmenityDetail) -> str:
        """Display place categories."""
        categories = list(obj.geo_place.categories.all())
        return _format_categories_list(categories)

    @display(description=_("Opening Hours"), boolean=True)
    def has_opening_hours(self, obj: AmenityDetail) -> bool:
        """Check if opening hours are defined."""
        return bool(obj.opening_hours)

    @display(description=_("Phones"), boolean=True)
    def has_phones(self, obj: AmenityDetail) -> bool:
        """Check if phone numbers are defined."""
        return bool(obj.phones)
