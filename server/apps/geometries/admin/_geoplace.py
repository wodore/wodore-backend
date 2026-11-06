from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, cast, override

from django_admin_runner.admin import CommandRunnerModelAdminMixin

from django import forms
from django.contrib import admin
from django.db import models as db_models
from django.db.models.functions import Lower
from django.forms import ModelForm
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import (
    AutocompleteSelectMultipleFilter,
    ChoicesCheckboxFilter,
    ChoicesDropdownFilter,
)
from unfold.decorators import display

from server.apps.envvars.registry import resolve_setting
from server.apps.manager.admin import ModelAdmin
from server.apps.manager.widgets import UnfoldReadonlyJSONSuit
from server.apps.translations.admin_helpers import (
    DescriptionQualityFilter,
    LLMAdminMixin,
)
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..forms import GeoPlaceAdminFieldsets
from ..models import (
    AmenityDetail,
    GeoPlace,
    GeoPlaceCategory,
    GeoPlaceExternalLink,
    GeoPlaceParty,
    GeoPlaceSourceAssociation,
)
from ..utils import get_progress_bar

if TYPE_CHECKING:
    from server.apps.categories.models import Category

## Custom Admin Forms


class _GeoPlaceSourceAssociationForm(ModelForm[GeoPlaceSourceAssociation]):
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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

    @override
    def has_add_permission(self, request: HttpRequest, obj: Any) -> bool:  # type: ignore  # inline-admin default-param drift, plugin-less
        return False

    def has_delete_permission(self, _request, _obj):  # type: ignore  # inline-admin default-param drift, plugin-less
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

    @override
    def has_add_permission(self, request: HttpRequest, obj: Any) -> bool:  # type: ignore  # inline-admin default-param drift, plugin-less
        return True

    def has_delete_permission(self, _request, _obj):  # type: ignore  # inline-admin default-param drift, plugin-less
        return True


def _format_categories_list(categories: Sequence[Category]) -> str:
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


class GeoPlaceCategoryInlineForm(forms.ModelForm[GeoPlaceCategory]):
    """Category association form with a schema-driven extra editor.

    The ``extra`` field renders through Unfold's jedison-based
    ``UnfoldAdminJSONSchemaWidget`` with the schema resolved for the
    row's category (own category first, else parent) — the editor UI
    is generated from the JSON Schema. Rows without a schema keep
    the plain JSON textarea. Validation funnels through
    ``GeoPlaceCategory.validate_attributes`` — the same helper
    ``clean()`` and the import use (D3).
    """

    class Meta:
        model = GeoPlaceCategory
        fields = ("category", "classifier", "extra")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from unfold.widgets import UnfoldAdminJSONSchemaWidget

        from server.apps.geometries.models import GeoPlaceCategory, resolve_extra_schema

        # Narrow the generic ModelForm instance (its ``instance`` types
        # as the abstract base — the FK-id attribute is only known on
        # the concrete model).
        instance = cast(GeoPlaceCategory, self.instance)
        if instance.category_id:
            schema_row = resolve_extra_schema(instance.category)
            if schema_row is not None and schema_row.schema:
                self.fields["extra"].widget = UnfoldAdminJSONSchemaWidget(
                    attrs={"schema": schema_row.schema}
                )

    @override
    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        extra = cleaned.get("extra") or {}
        if not isinstance(extra, dict):
            raise forms.ValidationError({"extra": _("Extra must be a JSON object")})
        category = cleaned.get("category") or self.instance.category
        GeoPlaceCategory.validate_attributes(category, cleaned.get("classifier"), extra)
        return cleaned


class GeoPlaceCategoryInline(unfold_admin.TabularInline):
    """GeoPlace category association inline with operation mode."""

    model = GeoPlaceCategory
    form = GeoPlaceCategoryInlineForm
    tab = True
    fields = (
        "category",
        "classifier",
        "extra",
    )
    autocomplete_fields = ("category", "classifier")
    extra = 1
    show_change_link = True
    verbose_name = _("Category")

    @override
    def formfield_for_foreignkey(
        self,
        db_field: db_models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ):
        """Scope the classifier autocomplete to the kind registry's
        allowed subtrees (PLACE_KINDS — today mode.*; registry-driven
        instead of hardcoded, geoplace-kinds task 1.4)."""
        from server.apps.categories.models import Category

        from ..kinds import PLACE_KINDS

        if db_field.name == "classifier":
            allowed_roots = sorted(
                {root for kind in PLACE_KINDS.values() for root in kind.classifiers}
            )
            kwargs["queryset"] = Category.objects.filter(
                parent__slug__in=allowed_roots
            ).order_by("order")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @override
    def has_add_permission(self, request: HttpRequest, obj: Any) -> bool:  # type: ignore  # inline-admin default-param drift, plugin-less
        return True

    def has_delete_permission(self, _request, _obj):  # type: ignore  # inline-admin default-param drift, plugin-less
        return True


class GeoPlacePartyInline(unfold_admin.TabularInline):
    """GeoPlace party association inline (role-classified)."""

    model = GeoPlaceParty
    tab = True
    fields = ("party", "role", "order")
    autocomplete_fields = ("party", "role")
    extra = 0
    show_change_link = True
    verbose_name = _("Party")

    @override
    def formfield_for_foreignkey(
        self,
        db_field: db_models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ):
        """Scope the role autocomplete to the role.* subtree."""
        from server.apps.categories.models import Category

        if db_field.name == "role":
            kwargs["queryset"] = Category.objects.filter(parent__slug="role").order_by(
                "order"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


## ADMIN


@admin.register(GeoPlace)
class GeoPlaceAdmin(LLMAdminMixin, CommandRunnerModelAdminMixin, ModelAdmin):
    """
    Admin interface for GeoPlace model.

    Provides management of curated geographic places imported from
    GeoNames and other sources.
    """

    form = required_i18n_fields_form_factory("name")

    @override
    def get_form(
        self,
        request: HttpRequest,
        obj: Any = None,
        change: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Render ``GeoPlace.extra`` through the JSON-Schema widget with
        the place's kind-root schema (task 2.6) — same editor as the
        association extra."""
        form_class = super().get_form(request, obj=obj, change=change, **kwargs)
        if obj is not None and getattr(obj, "pk", None):
            from ..kinds import kind_root_category
            from ..models import resolve_extra_schema

            categories = list(obj.categories.all())
            root = kind_root_category(categories)
            schema_row = resolve_extra_schema(root) if root is not None else None
            if schema_row is not None and schema_row.schema.get("properties"):
                from unfold.widgets import UnfoldAdminJSONSchemaWidget

                form_class.base_fields["extra"].widget = UnfoldAdminJSONSchemaWidget(
                    attrs={"schema": schema_row.schema}
                )
        return form_class

    list_filter_submit = True  # Add submit button for filters
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    # domain derives on write from the category tree
    # (geoplace-category-tree) — never hand-edited; kind is the
    # derived anchor category FK (first association by order/slug,
    # maintained by the rederive receiver on association writes)
    readonly_fields = ("domain", "kind")

    list_display = (
        "category_icon",
        "title",
        "categories_display",
        "country_code",
        "elevation_display",
        "sources_display",
        "importance_display",
        "review_tag",
        "description_quality_display",
        "visits_30d",
        "visits_365d",
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
        DescriptionQualityFilter,
        "is_public",
        "is_active",
        (
            "categories",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by categories with autocomplete
        (
            "categories__parent",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by category parent (e.g. all accommodations)
        (
            "source_set",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by source organization (geonames, osm, wodore, ...)
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
        "visits_30d",
        "visits_365d",
        "created",
        "modified",
    )

    fieldsets = GeoPlaceAdminFieldsets  # type: ignore  # admin fieldsets/list_filter typing drift (lazy gettext)

    list_per_page = 50

    @override
    def get_queryset(self, request: HttpRequest):
        from server.apps.visits.models import visit_window_annotation

        return (
            super()
            .get_queryset(request)
            .prefetch_related("categories__parent")
            .annotate(
                visits_30d=visit_window_annotation(GeoPlace, days=30),
                visits_365d=visit_window_annotation(GeoPlace, days=365),
            )
        )

    def get_inlines(self, _request, _obj):  # type: ignore  # admin hook signature drift vs stubs
        """Return inlines for admin."""
        return [
            GeoPlaceCategoryInline,
            GeoPlaceSourceAssociationInline,
            GeoPlaceExternalLinkInline,
            GeoPlacePartyInline,
        ]

    @override
    def save_formset(
        self,
        request: HttpRequest,
        form: Any,
        formset: Any,
        change: bool,
    ) -> None:
        """Manual association edits protect the place from import overwrites.

        OpenSpec geoplace-parties decision 7: associations carry no
        automatic tracking, so the inline formset save explicitly marks
        the place ``is_modified`` and records the association in
        ``protected_fields`` — parties role-scoped
        (``{"parties": ["role.brand"]}``, recording the roles the edit
        touched), links and categories flat (``"links"`` /
        ``"categories"`` — no scoping axis needed yet).
        """
        protected_inline_models = (
            GeoPlaceParty,
            GeoPlaceExternalLink,
            GeoPlaceCategory,
        )
        if formset.has_changed() and formset.model in protected_inline_models:
            place = form.instance
            place.is_modified = True
            protected = list(place.protected_fields or [])

            if formset.model is GeoPlaceParty:
                # Role-scoped: record the roles this edit touched. A
                # legacy flat "parties" entry (all roles) is kept —
                # protection never narrows silently.
                if "parties" in protected:
                    place.save(update_fields=["is_modified"])
                else:
                    changed_roles: set[str] = set()
                    for obj, _data in formset.changed_objects:
                        if obj.role_id:
                            changed_roles.add(obj.role.identifier)
                    for obj in (*formset.new_objects, *formset.deleted_objects):
                        if obj.role_id:
                            changed_roles.add(obj.role.identifier)
                    scoped: set[str] = set()
                    for entry in protected:
                        if isinstance(entry, dict) and isinstance(
                            entry.get("parties"), list
                        ):
                            scoped.update(str(role) for role in entry["parties"])
                    protected = [
                        entry
                        for entry in protected
                        if not (isinstance(entry, dict) and "parties" in entry)
                    ]
                    protected.append({"parties": sorted(scoped | changed_roles)})
                    place.protected_fields = protected
                    place.save(update_fields=["is_modified", "protected_fields"])
            else:
                field_name = (
                    "links" if formset.model is GeoPlaceExternalLink else "categories"
                )
                if field_name not in protected:
                    protected.append(field_name)
                    place.protected_fields = protected
                    place.save(update_fields=["is_modified", "protected_fields"])
                else:
                    place.save(update_fields=["is_modified"])

        super().save_formset(request, form, formset, change)

    @override
    def get_urls(self) -> list[Any]:
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

    def tilemap_view(self, request: HttpRequest):
        """Interactive tile map with clustering debug and overlay filtering."""
        from server.apps.categories.models import Category
        from server.apps.geometries.config.osm_categories import CATEGORY_REGISTRY

        category_slugs = [cat.category for cat in CATEGORY_REGISTRY]
        categories = (
            Category.objects.contract_groups()
            .filter(slug__in=category_slugs, is_active=True)
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
            "martin_tile_url": resolve_setting("MARTIN_TILE_URL"),
            "is_fullwidth": "1",
        }
        return TemplateResponse(request, "admin/geometries_tilemap.html", context)

    # Display methods

    @display(description="")
    def category_icon(self, obj: GeoPlace) -> str:
        """Display the first category's symbol icon with priority: detailed → simple → mono."""
        # Get first category (ordered by the through model's order field)
        first_category = obj.categories.order_by("order", "slug").first()
        if not first_category:
            return ""

        # Try symbols in priority order: detailed → simple → mono
        for symbol_attr in ["symbol_color", "symbol_primitive", "symbol_mono"]:
            symbol = getattr(first_category, symbol_attr, None)
            if symbol and symbol.svg_file and symbol.svg_file.name:
                return mark_safe(
                    f'<img src="{symbol.svg_file.url}" width="25px" '
                    f'alt="{first_category.slug}" title="{first_category.name_i18n}"/>'
                )
        return ""

    @display(header=True, ordering=Lower("name"))
    def title(self, obj: GeoPlace) -> tuple[str, SafeString]:
        """Display name and slug in the same column, like Hut admin."""
        return (obj.name_i18n, mark_safe(f"<small><code>{obj.slug}</code></small>"))

    @display(description=_("Categories"))
    def categories_display(self, obj: GeoPlace) -> str:
        """Display categories with parents if available."""
        categories = list(obj.categories.all())
        return _format_categories_list(categories)

    @display(description=_("Kind"))
    def kind_display(self, obj: GeoPlace) -> str:
        """The anchoring kind category (first by order/slug) — derived.

        Not a stored column: the kind IS the first category
        association (the same anchor ``domain`` derives its super-root
        from). Editable via the Categories inline below.
        """
        first = obj.categories.order_by("order", "slug").first()
        return first.identifier if first else "—"

    @display(description=_("Elevation"))
    def elevation_display(self, obj: GeoPlace) -> str:
        """Display elevation with unit."""
        if obj.elevation is not None:
            return f"{obj.elevation} m"
        return "-"

    @display(description=_("Sources"))
    def sources_display(self, obj: GeoPlace) -> str:
        """Display source organizations as icons."""

        sources = obj.source_associations.select_related("organization").all()  # type: ignore  # dynamic attr: plugin-less inference gap
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

    @display(description=_("Visits 30d"), ordering="visits_30d")
    def visits_30d(self, obj: GeoPlace) -> int:
        """Visit sum over the last 30 days (openspec: place-visit-counter)."""
        return obj.visits_30d  # type: ignore  # dynamic attr: plugin-less inference gap

    @display(description=_("Visits 1y"), ordering="visits_365d")
    def visits_365d(self, obj: GeoPlace) -> int:
        """Visit sum over the last year (openspec: place-visit-counter)."""
        return obj.visits_365d  # type: ignore  # dynamic attr: plugin-less inference gap

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
            "rework": "danger",
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
    operating status, and contact information.
    """

    list_display = (
        "place_name",
        "place_categories",
        "operating_status",
        "has_opening_hours",
        "has_phones",
        "created",
        "modified",
    )

    list_display_links = ("place_name",)

    list_filter = (
        "operating_status",
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

    autocomplete_fields = ("geo_place",)

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

    @override
    def get_queryset(self, request: HttpRequest):
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
