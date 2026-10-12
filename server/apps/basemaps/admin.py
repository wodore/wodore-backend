"""Unfold admin for the basemaps catalog.

JSONFields (``style``, ``config``, …) render through the repo-wide
``jsoneditor`` widget (INSTALLED_APPS) — the "variable-aware" editor is
a follow-up once parameters settle. The MapLayer change page gets a
live style preview (MapLibre GL, resolved mode) via ``<id>/preview/``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .models import (
    MapCoverage,
    MapLayer,
    MapLayerAttribution,
    MapLayerCategory,
    MapLayerParameter,
    MapParameter,
    MapSlot,
)
from .resolution import style_endpoint_url


class MapLayerParameterInline(admin.TabularInline):
    """Parameter links with per-layer default override."""

    model = MapLayerParameter
    tab = True
    extra = 0
    autocomplete_fields = ("parameter",)


class MapLayerCategoryInline(admin.TabularInline):
    """Category links (filters/legends)."""

    model = MapLayerCategory
    tab = True
    extra = 0
    autocomplete_fields = ("category",)


class MapLayerAttributionInline(admin.TabularInline):
    """Ordered attribution links to organizations."""

    model = MapLayerAttribution
    tab = True
    extra = 0
    autocomplete_fields = ("organization",)


@admin.register(MapSlot)
class MapSlotAdmin(ModelAdmin):
    """Slot lookup admin."""

    list_display = ("slug", "label_i18n", "order")
    list_editable = ("order",)
    search_fields = ("slug", "label")


@admin.register(MapParameter)
class MapParameterAdmin(ModelAdmin):
    """Parameter registry admin."""

    list_display = ("slug", "kind", "label_i18n", "default_preview")
    list_filter = ("kind",)
    search_fields = ("slug", "label", "description")

    @display(description=_("Default"))
    def default_preview(self, obj: MapParameter) -> str:
        default = obj.default
        text = repr(default)
        return text if len(text) <= 80 else f"{text[:77]}…"


@admin.register(MapCoverage)
class MapCoverageAdmin(ModelAdmin):
    """Coverage polygon admin (raw geometry; map widget with WEP010 ph1)."""

    list_display = ("slug", "name", "bbox_display")
    search_fields = ("slug", "name")

    @display(description=_("Bbox (W,S,E,N)"))
    def bbox_display(self, obj: MapCoverage) -> str:
        bbox = obj.bbox
        return ", ".join(f"{coord:.3f}" for coord in bbox) if bbox else "—"


@admin.register(MapLayer)
class MapLayerAdmin(ModelAdmin):
    """Layer curation: variants, styles, parameters, links, preview."""

    list_display = (
        "slug",
        "spec",
        "role",
        "order",
        "show",
        "is_active",
        "is_default",
        "style_kind",
        "slot",
    )
    list_filter = ("role", "spec", "is_active", "show", "slot")
    list_editable = ("order",)
    search_fields = ("slug", "name", "description")
    autocomplete_fields = (
        "slot",
        "coverage",
        "fallback",
        "license",
    )
    inlines: ClassVar[tuple[type[admin.TabularInline], ...]] = (
        MapLayerParameterInline,
        MapLayerCategoryInline,
        MapLayerAttributionInline,
    )
    readonly_fields: ClassVar[tuple[str, ...]] = ("style_serving_url",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "slug",
                    "spec",
                    "role",
                    "name",
                    "description",
                    "icon",
                    "icon_badge",
                    "slot",
                    "order",
                    "show",
                    "is_active",
                    "is_default",
                )
            },
        ),
        (
            _("Style"),
            {
                "fields": (
                    "style",
                    "style_url",
                    "min_zoom",
                    "max_zoom",
                    "style_serving_url",
                )
            },
        ),
        (
            _("Placement & fallback"),
            {"fields": ("coverage", "fallback_min_zoom", "fallback", "anchors")},
        ),
        (
            _("Content & interaction"),
            {"fields": ("config", "interaction", "preview_url")},
        ),
        (_("Legal"), {"fields": ("license",)}),
    )

    @display(description=_("Style"), boolean=True)
    def style_kind(self, obj: MapLayer) -> bool:
        return obj.style is not None

    def get_urls(self) -> list[Any]:
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="basemaps_maplayer_preview",
            ),
        ]
        return custom + urls

    def preview_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        """Live MapLibre preview of the layer's resolved style."""
        layer = get_object_or_404(MapLayer, pk=object_id)
        style_url = ""
        if layer.style is not None:
            style_url = style_endpoint_url(layer.slug, layer.spec)
        context = {
            **self.admin_site.each_context(request),
            "layer": layer,
            "style_url": style_url,
            "external_style_url": layer.style_url or "",
            "title": _("Preview: %(layer)s") % {"layer": layer.slug},
        }
        return render(request, "admin/basemaps/maplayer/preview.html", context)

    def style_serving_url(self, obj: MapLayer) -> str:
        """The public style endpoint URL for this layer variant."""
        if not obj.pk:
            return "—"
        if obj.style is not None:
            return style_endpoint_url(obj.slug, obj.spec)
        return obj.style_url or "—"

    style_serving_url.short_description = _("Served at")  # type: ignore[attr-defined]
