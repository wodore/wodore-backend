import contextlib

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from django.contrib import admin
from django.db import models
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.admin import TabularInline
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .models import WeatherCode, WeatherCodeSymbolCollection, WeatherCodeSymbol


class WeatherCodeSymbolInline(TabularInline):
    """Inline for displaying WeatherCodeSymbol mappings."""

    model = WeatherCodeSymbol
    extra = 0
    fields = (
        "collection_display",
        "weather_code_display",
        "symbol_day_preview",
        "symbol_night_preview",
        "symbol_day",
        "symbol_night",
    )
    readonly_fields = (
        "collection_display",
        "weather_code_display",
        "symbol_day_preview",
        "symbol_night_preview",
    )
    can_delete = False
    show_change_link = True

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        # Optimize with select_related to avoid N+1 queries
        return qs.select_related(
            "weather_code",
            "collection",
            "symbol_day",
            "symbol_night",
        )

    @display(description=_("Collection"))
    def collection_display(self, obj):
        """Display collection slug."""
        if obj.collection:
            return obj.collection.slug
        return "-"

    @display(description=_("Weather Code"))
    def weather_code_display(self, obj):
        """Display weather code."""
        if obj.weather_code:
            return f"WMO {obj.weather_code.code}"
        return "-"

    @display(description=_("Day"))
    def symbol_day_preview(self, obj):
        """Show day symbol preview."""
        try:
            if obj.symbol_day and obj.symbol_day.svg_file:
                return mark_safe(
                    f'<img src="{obj.symbol_day.svg_file.url}" width="30" height="30" '
                    f'style="object-fit:contain;" title="{obj.symbol_day.slug}" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Night"))
    def symbol_night_preview(self, obj):
        """Show night symbol preview."""
        try:
            if obj.symbol_night and obj.symbol_night.svg_file:
                return mark_safe(
                    f'<img src="{obj.symbol_night.svg_file.url}" width="30" height="30" '
                    f'style="object-fit:contain;" title="{obj.symbol_night.slug}" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')


class WeatherCodeSymbolInlineForWeatherCode(WeatherCodeSymbolInline):
    """Inline showing which collections this weather code appears in."""

    fk_name = "weather_code"
    fields = (
        "collection_display",
        "symbol_day_preview",
        "symbol_night_preview",
        "symbol_day",
        "symbol_night",
    )
    readonly_fields = (
        "collection_display",
        "symbol_day_preview",
        "symbol_night_preview",
    )


@admin.register(WeatherCode)
class WeatherCodeAdmin(ModelAdmin):
    """Admin panel for WeatherCode model."""

    list_display = (
        "code",
        "slug",
        "symbol_preview_day",
        "symbol_preview_night",
        "description_preview_day",
        "category_display",
    )
    list_display_links = ("code", "slug")
    search_fields = (
        "code",
        "slug",
        "description_day",
        "description_night",
    )
    list_filter = (
        "category",
        "code",
    )
    readonly_fields = (
        "id",
        "created",
        "modified",
        "slug",
    )
    # Note: Inlines disabled for performance - use WeatherCodeSymbol admin to manage symbols
    # inlines = [WeatherCodeSymbolInlineForWeatherCode]
    fieldsets = (
        (
            _("WMO Code"),
            {
                "fields": (
                    "code",
                    "slug",
                    "category",
                )
            },
        ),
        (
            _("Descriptions"),
            {
                "fields": (
                    "description_day",
                    "description_night",
                )
            },
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "created",
                    "modified",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        qs = qs.select_related("category")
        # Prefetch only weather-icons-filled symbols for preview display
        qs = qs.prefetch_related(
            models.Prefetch(
                "symbols",
                queryset=WeatherCodeSymbol.objects.filter(
                    collection__slug="weather-icons-filled"
                ).select_related(
                    "collection",
                    "symbol_day",
                    "symbol_night",
                ),
            )
        )
        return qs

    @display(description=_("Category"))
    def category_display(self, obj):
        """Display category."""
        if obj.category:
            if obj.category.parent:
                return f"{obj.category.parent.slug}.{obj.category.slug}"
            return obj.category.slug
        return "-"

    @display(description=_("Day"))
    def symbol_preview_day(self, obj):
        """Show day symbol preview from weather-icons-filled collection."""
        try:
            # Use prefetched symbols to avoid extra queries
            for code_symbol in obj.symbols.all():
                if code_symbol.collection.slug == "weather-icons-filled":
                    if code_symbol.symbol_day and code_symbol.symbol_day.svg_file:
                        return mark_safe(
                            f'<img src="{code_symbol.symbol_day.svg_file.url}" width="40" height="40" '
                            f'style="object-fit:contain;" title="{code_symbol.symbol_day.slug}" />'
                        )
                    break
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Night"))
    def symbol_preview_night(self, obj):
        """Show night symbol preview from weather-icons-filled collection."""
        try:
            # Use prefetched symbols to avoid extra queries
            for code_symbol in obj.symbols.all():
                if code_symbol.collection.slug == "weather-icons-filled":
                    if code_symbol.symbol_night and code_symbol.symbol_night.svg_file:
                        return mark_safe(
                            f'<img src="{code_symbol.symbol_night.svg_file.url}" width="40" height="40" '
                            f'style="object-fit:contain;" title="{code_symbol.symbol_night.slug}" />'
                        )
                    break
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Day Description"))
    def description_preview_day(self, obj):
        """Show truncated day description."""
        if obj.description_day:
            desc = obj.description_day
            if len(desc) > 40:
                desc = desc[:37] + "..."
            return desc
        return "-"


class WeatherCodeSymbolInlineForCollection(WeatherCodeSymbolInline):
    """Inline showing all symbol mappings in this collection."""

    fk_name = "collection"
    fields = (
        "weather_code_display",
        "symbol_day_preview",
        "symbol_night_preview",
        "symbol_day",
        "symbol_night",
    )
    readonly_fields = (
        "weather_code_display",
        "symbol_day_preview",
        "symbol_night_preview",
    )


@admin.register(WeatherCodeSymbolCollection)
class WeatherCodeSymbolCollectionAdmin(ModelAdmin):
    """Admin panel for WeatherCodeSymbolCollection model."""

    list_display = (
        "slug",
        "source_org_display",
        "symbol_count",
        "created",
    )
    list_display_links = ("slug",)
    search_fields = (
        "slug",
        "source_org__name",
        "source_org__slug",
    )
    list_filter = ("source_org",)
    readonly_fields = (
        "id",
        "created",
        "modified",
        "symbol_count",
    )
    # Note: Inlines disabled for performance - use WeatherCodeSymbol admin to manage symbols
    # inlines = [WeatherCodeSymbolInlineForCollection]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "slug",
                    "source_org",
                )
            },
        ),
        (
            _("Statistics"),
            {"fields": ("symbol_count",)},
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "created",
                    "modified",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        qs = qs.select_related("source_org")
        # Annotate with symbol count for efficient list display
        qs = qs.annotate(symbols_count=models.Count("symbols"))
        # Note: Removed prefetch since inlines are disabled for performance
        return qs

    @display(description=_("Organization"))
    def source_org_display(self, obj):
        """Display source organization."""
        if obj.source_org:
            return obj.source_org.name or obj.source_org.slug
        return "-"

    @display(description=_("Symbol Count"))
    def symbol_count(self, obj):
        """Display number of symbols in collection."""
        # Use annotated count if available, otherwise fall back to query
        return getattr(obj, "symbols_count", obj.symbols.count() if obj.pk else 0)


@admin.register(WeatherCodeSymbol)
class WeatherCodeSymbolAdmin(ModelAdmin):
    """Admin panel for WeatherCodeSymbol model."""

    list_display = (
        "weather_code_display",
        "collection_display",
        "symbol_preview_day",
        "symbol_preview_night",
    )
    list_display_links = ("weather_code_display",)
    search_fields = (
        "weather_code__code",
        "weather_code__slug",
        "collection__slug",
        "symbol_day__slug",
        "symbol_night__slug",
    )
    list_filter = (
        "collection",
        "weather_code__category",
    )
    readonly_fields = (
        "id",
        "created",
        "modified",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "weather_code",
                    "collection",
                )
            },
        ),
        (
            _("Symbols"),
            {
                "fields": (
                    "symbol_day",
                    "symbol_night",
                )
            },
        ),
        (
            _("Metadata"),
            {
                "fields": (
                    "created",
                    "modified",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.select_related(
            "weather_code",
            "collection",
            "symbol_day",
            "symbol_night",
        )

    @display(description=_("Weather Code"))
    def weather_code_display(self, obj):
        """Display weather code."""
        if obj.weather_code:
            return f"WMO {obj.weather_code.code} ({obj.weather_code.slug})"
        return "-"

    @display(description=_("Collection"))
    def collection_display(self, obj):
        """Display collection."""
        if obj.collection:
            return obj.collection.slug
        return "-"

    @display(description=_("Day Symbol"))
    def symbol_preview_day(self, obj):
        """Show day symbol preview."""
        try:
            if obj.symbol_day and obj.symbol_day.svg_file:
                return mark_safe(
                    f'<img src="{obj.symbol_day.svg_file.url}" width="30" height="30" '
                    f'style="object-fit:contain;" title="{obj.symbol_day.slug}" />'
                )
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')

    @display(description=_("Night Symbol"))
    def symbol_preview_night(self, obj):
        """Show night symbol preview."""
        try:
            if obj.symbol_night and obj.symbol_night.svg_file:
                img = (
                    f'<img src="{obj.symbol_night.svg_file.url}" '
                    f'width="30" height="30" style="object-fit:contain;" '
                    f'title="{obj.symbol_night.slug}" />'
                )
                return mark_safe(img)
        except Exception:
            pass
        return mark_safe('<span style="color:#999;">-</span>')
