import json
from typing import ClassVar

from django import forms
from django.conf import settings
from django.contrib import admin
from django.forms import ModelForm
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.db.models.functions import Lower

from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import (
    AutocompleteSelectMultipleFilter,
    ChoicesCheckboxFilter,
    ChoicesDropdownFilter,
)
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
from ..utils import get_progress_bar


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
    list_filter_submit = True  # Add submit button for filters
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    list_display = (
        "category_icon",
        "title",
        "categories_display",
        "country_code",
        "elevation_display",
        "sources_display",
        "importance_display",
        "review_tag",
        "is_public",
        "is_active",
        "timestamps_display",
    )

    list_display_links = (
        "category_icon",
        "title",
    )

    list_filter = (
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
        "is_public",
        "is_active",
        (
            "categories",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by categories with autocomplete
        (
            "country_code",
            ChoicesDropdownFilter,
        ),  # Filter by country with dropdown
    )

    search_fields = (
        "name",
        "name_i18n",
        "slug",
        "categories__name_i18n",
        "categories__slug",
    )

    autocomplete_fields = ("parent",)

    readonly_fields = (
        "slug",
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
        "importance",
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

    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        custom_urls = [
            path(
                "tilemap/",
                self.admin_site.admin_view(self.tilemap_view),
                name="geometries_geoplace_tilemap",
            ),
        ]
        return custom_urls + urls

    def tilemap_view(self, request):
        """Interactive tile map with clustering debug and overlay filtering."""
        from server.apps.categories.models import Category
        from server.apps.geometries.config.osm_categories import CATEGORY_REGISTRY

        category_slugs = [cat.category for cat in CATEGORY_REGISTRY]
        categories = (
            Category.objects.filter(
                parent__isnull=True, slug__in=category_slugs, is_active=True
            )
            .order_by("order", "slug")
            .values("slug", "name_i18n", "color")
        )

        overlay_categories = [
            {
                "slug": cat["slug"],
                "name": cat["name_i18n"] or cat["slug"],
                "color": cat["color"] or "#808080",
            }
            for cat in categories
        ]

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Tile Map"),
            "has_permission": True,
            "overlay_categories_json": json.dumps(overlay_categories),
            "martin_tile_url": getattr(
                settings, "MARTIN_TILE_URL", "http://localhost:8075"
            ),
            "is_fullwidth": "1",
        }
        return TemplateResponse(request, "admin/geometries_tilemap.html", context)

    # Display methods

    @display(description="")
    def category_icon(self, obj):
        """Display the first category's symbol icon with priority: detailed → simple → mono."""
        # Get first category (ordered by the through model's order field)
        first_category = obj.categories.order_by("order", "slug").first()
        if not first_category:
            return ""

        # Try symbols in priority order: detailed → simple → mono
        for symbol_attr in ["symbol_detailed", "symbol_simple", "symbol_mono"]:
            symbol = getattr(first_category, symbol_attr, None)
            if symbol and symbol.svg_file and symbol.svg_file.name:
                return mark_safe(
                    f'<img src="{symbol.svg_file.url}" width="25px" '
                    f'alt="{first_category.slug}" title="{first_category.name_i18n}"/>'
                )
        return ""

    @display(header=True, ordering=Lower("name"))
    def title(self, obj):
        """Display name and slug in the same column, like Hut admin."""
        return (obj.name_i18n, mark_safe(f"<small><code>{obj.slug}</code></small>"))

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

    @display(description=_("Sources"))
    def sources_display(self, obj: GeoPlace) -> str:
        """Display source organizations as icons."""

        sources = obj.source_associations.select_related("organization").all()
        if not sources:
            return "-"

        imgs = []
        for source in sources:
            org = source.organization
            if org.logo:
                # Create link to source if available
                if source.source_id:
                    # For OSM, create a link to the OSM page
                    if org.slug == "osm":
                        osm_type, osm_id = source.source_id.split("/")
                        if osm_type == "node":
                            osm_url = f"https://www.openstreetmap.org/node/{osm_id}"
                        elif osm_type == "way":
                            osm_url = f"https://www.openstreetmap.org/way/{osm_id}"
                        else:
                            osm_url = (
                                f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
                            )
                        img_html = f'<a href="{osm_url}" target="_blank" title="{org.name_i18n}"><img class="inline pr-1" src="{org.logo.url}" width="20px" alt="{org.slug}"/></a>'
                    else:
                        img_html = f'<span title="{org.name_i18n}"><img class="inline pr-1" src="{org.logo.url}" width="20px" alt="{org.slug}"/></span>'
                else:
                    img_html = f'<span title="{org.name_i18n}"><img class="inline pr-1" src="{org.logo.url}" width="20px" alt="{org.slug}"/></span>'
                imgs.append(img_html)

        return mark_safe(f"<span>{''.join(imgs)}</span>")

    @display(description=_("Importance"), ordering="importance")
    def importance_display(self, obj: GeoPlace) -> str:
        """Display importance as a progress bar with blue color range."""
        # Use blue color gradient
        return get_progress_bar(
            value=obj.importance,
            max_value=100,
            color="#2196F3",  # Blue color
            show_text=True,
            active=True,
        )

    @display(description=_("Created/Modified"), ordering="modified")
    def timestamps_display(self, obj: GeoPlace) -> str:
        """Display created and modified timestamps in one column with small font."""
        created = obj.created.strftime("%Y-%m-%d %H:%M") if obj.created else "-"
        modified = obj.modified.strftime("%Y-%m-%d %H:%M") if obj.modified else "-"

        return format_html(
            '<div style="font-size: 11px; line-height: 1.4;">'
            '<div style="color: #6b7280;">Created: {}</div>'
            '<div style="color: #6b7280;">Modified: {}</div>'
            "</div>",
            created,
            modified,
        )

    @display(
        description=_("Review"),
        label={
            "new": "warning",
            "review": "info",
            "work": "danger",
            "done": "success",
        },
    )
    def review_tag(self, obj: GeoPlace) -> str:
        """Display review status as colored label."""
        return obj.review_status

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
        "geo_place__categories__name_i18n",
        "geo_place__categories__slug",
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
