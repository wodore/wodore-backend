# Models
import contextlib
from typing import ClassVar

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from django.contrib import admin
from django.db.models import Count
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.admin import TabularInline
from unfold.contrib.filters.admin import (
    AutocompleteSelectMultipleFilter,
    ChoicesCheckboxFilter,
)
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .forms import SymbolAdminFieldsets
from .models import (
    Icon,
    IconCuratedList,
    IconCuratedListEntry,
    IconKeyword,
    Symbol,
    SymbolCollection,
    SymbolGroup,
)


@admin.register(Symbol)
class SymbolAdmin(ModelAdmin):
    """Admin panel for Symbol model."""

    fieldsets = SymbolAdminFieldsets
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    list_display = (
        "svg_preview",
        "slug",
        "style",
        "search_text_display",
        "license_display",
        "source_display",
        "review_status_display",
    )
    list_display_links = ("svg_preview", "slug")
    search_fields = ("slug", "search_text", "source_ident", "author")
    list_filter = (
        "style",
        "source_org",
        "license",
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
        "uploaded_by_user",
        "is_active",
    )
    readonly_fields = (
        "id",
        "svg_preview_inline",
        "created",
        "modified",
        "uploaded_date",
    )

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_user:  # pyright: ignore[reportAttributeAccessIssue]  # model attr: django-stubs gap
            obj.uploaded_by_user = request.user  # pyright: ignore[reportAttributeAccessIssue]  # model attr: django-stubs gap
        super().save_model(request, obj, form, change)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.select_related("license", "source_org", "uploaded_by_user")

    @display(description=_("SVG"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def svg_preview(self, obj):
        """Show SVG preview in list view."""
        try:
            if obj.svg_file:
                return mark_safe(
                    f'<img src="{obj.svg_file.url}" width="40" height="40" style="object-fit:contain;" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">No file</span>')

    @display(description=_("Preview"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def svg_preview_inline(self, obj):
        """Show SVG preview inline in the form."""
        try:
            if obj.svg_file:
                return mark_safe(
                    f'<div style="padding:15px;background:#f9f9f9;border:1px solid #ddd;border-radius:4px;text-align:center;margin-top:10px;">'
                    f'<img src="{obj.svg_file.url}" width="64" height="64" style="object-fit:contain;" />'
                    f"</div>"
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">No file uploaded</span>')

    @display(description=_("Search Text"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def search_text_display(self, obj):
        """Show search text in list view."""
        if obj.search_text:
            text = (
                obj.search_text[:50] + "..."
                if len(obj.search_text) > 50
                else obj.search_text
            )
            return mark_safe(f'<small style="color:#666;">{text}</small>')
        return mark_safe('<small style="color:#999;">-</small>')

    @display(description=_("License"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def license_display(self, obj):
        """Show license with link."""
        if obj.license:
            link = mark_safe(
                f'<a href="{obj.license.url_i18n}" target="_blank">{obj.license.name_i18n}</a>'
            )
            return link, link
        return mark_safe("-"), mark_safe("-")

    @display(description=_("Source"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def source_display(self, obj):
        """Show source information."""
        parts = []
        if obj.author:
            parts.append(obj.author)
        if obj.source_org:
            parts.append(
                f'<i><a href="{obj.source_org.url}" target="_blank">{obj.source_org.name_i18n}</a></i>'
            )
        if obj.source_ident:
            parts.append(f"<small>ID: {obj.source_ident}</small>")

        if parts:
            source_text = mark_safe(" ".join(parts))
            return source_text, source_text
        return mark_safe("-"), mark_safe("-")

    @display(description=_("Status"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def review_status_display(self, obj):
        """Show review status."""
        return obj.get_review_status_display()


# TODO: Add SymbolTagAdmin if tags are implemented in the future
# @admin.register(SymbolTag)
# class SymbolTagAdmin(ModelAdmin):
#     """Admin panel for SymbolTag model."""
#     pass


@admin.register(SymbolGroup)
class SymbolGroupAdmin(SymbolAdmin):
    """Admin for the SymbolGroup proxy model (symbols grouped by slug)."""


# ---------------------------------------------------------------------------
# Icon library (openspec: icon-library)
# ---------------------------------------------------------------------------


class IconKeywordInline(TabularInline):
    """Localized keywords of an icon."""

    model = IconKeyword
    extra = 0
    fields = ("locale", "keyword", "keyword_folded")
    readonly_fields = ("keyword_folded",)
    search_fields = ("keyword", "keyword_folded")


@admin.register(Icon)
class IconAdmin(ModelAdmin):
    """Admin panel for Icon, scoped to one pack at a time.

    Volume (~6k rows/pack) makes pack scoping the entry point: the
    changelist defaults to the first pack via ``get_queryset`` unless a
    pack filter is active; keyword inlines and symbol-slot previews live
    on the change form.
    """

    list_display = (
        "slug",
        "name_i18n_display",
        "pack",
        "unicode_display",
        "category_display",
        "is_active",
        "symbol_previews",
        "order",
    )
    list_display_links = ("slug", "name_i18n_display")
    search_fields = ("slug", "name", "keywords__keyword", "keywords__keyword_folded")
    list_filter = (
        "pack",
        "is_active",
        # Autocomplete filter: a plain category <select> would render all
        # ~9k categories on every changelist load.
        ("category", AutocompleteSelectMultipleFilter),
    )
    list_select_related = (
        "pack",
        "category__parent",
        "symbol_detailed",
        "symbol_simple",
        "symbol_mono",
    )
    readonly_fields = ("id", "created", "modified")
    inlines = (IconKeywordInline,)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        # Default to one pack when no pack filter/search is active (list
        # volume). `term` is the autocomplete-widget query param — icon
        # autocomplete (curated-list inline) must search across packs.
        if not request.GET.get("pack__id__exact") and not (
            request.GET.get("q") or request.GET.get("term")
        ):
            first_pack = SymbolCollection.objects.order_by("slug").first()
            if first_pack is not None:
                qs = qs.filter(pack=first_pack)
        return qs

    @display(description=_("Name"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def name_i18n_display(self, obj):
        name = obj.name_i18n or obj.name or "-"
        return (name, "")  # header display requires a tuple

    @display(description=_("Unicode"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def unicode_display(self, obj):
        return obj.unicode or "-"

    @display(description=_("Category"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def category_display(self, obj):
        if obj.category is None:
            return ("-", "")
        group = obj.category.parent.slug if obj.category.parent_id else ""
        return (f"{group} → {obj.category.slug}", obj.category.slug)

    @display(description=_("Symbols"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def symbol_previews(self, obj):
        """Preview thumbnails of the three symbol slots."""
        cells = []
        for style in ("detailed", "simple", "mono"):
            symbol = getattr(obj, f"symbol_{style}", None)
            if symbol is not None and symbol.svg_file:
                cells.append(
                    f'<img src="{symbol.svg_file.url}" width="28" height="28" '
                    f'style="object-fit:contain;vertical-align:middle;" '
                    f'title="{style}" />'
                )
            else:
                cells.append(f'<span style="color:#ccc;" title="{style}">·</span>')
        return mark_safe("&nbsp;".join(cells))


@admin.register(SymbolCollection)
class SymbolCollectionAdmin(ModelAdmin):
    """Admin panel for icon packs."""

    list_display = ("slug", "source_org_display", "icon_count", "ref_display")
    list_display_links = ("slug",)
    search_fields = ("slug", "source_org__name")
    readonly_fields = ("created", "modified")

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        return super().get_queryset(request).annotate(_icon_count=Count("icons"))

    @display(description=_("Source Org"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def source_org_display(self, obj):
        name = obj.source_org.name_i18n if obj.source_org else "-"
        return (name, "")

    @display(description=_("Icons"), ordering="_icon_count")  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def icon_count(self, obj):
        return getattr(obj, "_icon_count", 0)

    @display(description=_("Imported ref"))  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def ref_display(self, obj):
        return (obj.extra or {}).get("ref", "-")


class IconCuratedListEntryInline(TabularInline):
    """Curated icons of a list (manual curation in the admin)."""

    model = IconCuratedListEntry
    extra = 0
    autocomplete_fields = ("icon",)


@admin.register(IconCuratedList)
class IconCuratedListAdmin(ModelAdmin):
    """Admin panel for curated icon shortlists (e.g. activities).

    Curation is manual: create a list, attach icons via the entry
    inline (icon autocomplete). The import never touches these rows.
    """

    list_display = ("slug", "name_i18n_display", "entry_count")
    list_display_links = ("slug",)
    search_fields = ("slug", "name")
    readonly_fields = ("created", "modified")
    inlines = (IconCuratedListEntryInline,)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        return super().get_queryset(request).annotate(_entry_count=Count("entries"))

    @display(description=_("Name"), header=True)  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def name_i18n_display(self, obj):
        name = getattr(obj, "name_i18n", "") or obj.name or "-"
        return (name, "")

    @display(description=_("Icons"), ordering="_entry_count")  # pyright: ignore[reportArgumentType]  # _StrPromise vs str: unfold stub gap
    def entry_count(self, obj):
        return getattr(obj, "_entry_count", 0)
