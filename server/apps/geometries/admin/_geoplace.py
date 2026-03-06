from typing import ClassVar

from django import forms
from django.contrib import admin
from django.forms import ModelForm
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.manager.widgets import UnfoldReadonlyJSONSuit
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..models import (
    GeoPlace,
    GeoPlaceSourceAssociation,
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
        "import_date",
        "modified_date",
        "update_policy",
        "delete_policy",
    )
    readonly_fields = ("organization", "source_id", "import_date", "modified_date")
    extra = 0
    show_change_link = True
    verbose_name = _("Source")

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj):
        return False


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
        "place_type_display",
        "country_code",
        "elevation_display",
        "review_status_display",
        "is_public",
        "is_active",
    )

    list_display_links = ("name",)

    list_filter = (
        "review_status",
        "is_public",
        "is_active",
        "place_type__parent",  # Filter by category parent (e.g., terrain, transport)
        "place_type",
        "country_code",
    )

    search_fields = ("name", "name_i18n", "slug")

    autocomplete_fields = ("place_type", "parent")

    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "location_display",
        "created",
        "modified",
    )

    fieldsets = (
        (_("Identification"), {"fields": ("name", "name_i18n", "slug", "place_type")}),
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
            _("Description"),
            {"fields": ("description", "description_i18n")},
        ),
        (
            _("Review"),
            {
                "fields": (
                    "review_status",
                    "review_comment",
                    "detail_type",
                    "protected_fields",
                )
            },
        ),
        (
            _("Status"),
            {"fields": ("is_active", "is_public", "importance")},
        ),
        (_("Metadata"), {"classes": ["collapse"], "fields": ("created", "modified")}),
    )

    list_per_page = 50

    def get_inlines(self, request, obj):
        """Return inlines for admin."""
        return [
            GeoPlaceSourceAssociationInline,
        ]

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
