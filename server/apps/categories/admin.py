import contextlib

from django.conf import settings
from django.contrib import admin
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from unfold.contrib.filters.admin import AutocompleteSelectMultipleFilter
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .forms import category_admin_form_factory
from .models import Category


class ChildCategoryInline(admin.TabularInline):
    """Inline to show child categories in Category admin"""

    model = Category
    fk_name = "parent"
    tab = True  # Display as a tab in Unfold admin
    extra = 0
    fields = (
        "symbol_preview",
        "name_i18n",
        "slug",
        "order",
        "is_active",
        "view_link",
    )
    readonly_fields = (
        "symbol_preview",
        "name_i18n",
        "view_link",
        "slug",
    )
    can_delete = False  # Prevent deletion from inline
    verbose_name = _("Child Category")
    verbose_name_plural = _("Child Categories")
    autocomplete_fields = ("symbol_detailed", "symbol_simple", "symbol_mono")

    def get_queryset(self, request: HttpRequest):
        """Optimize queryset for inline display."""
        qs = super().get_queryset(request)
        return qs.select_related(
            "symbol_detailed", "symbol_simple", "symbol_mono"
        ).order_by("order", "slug")

    @display(description="")
    def symbol_preview(self, obj):
        """Display symbol preview."""
        if obj.symbol_detailed and obj.symbol_detailed.svg_file:
            return mark_safe(
                f'<img src="{obj.symbol_detailed.svg_file.url}" alt="{obj.slug}" style="width: 24px; height: 24px;" />'
            )
        elif obj.symbol_simple and obj.symbol_simple.svg_file:
            return mark_safe(
                f'<img src="{obj.symbol_simple.svg_file.url}" alt="{obj.slug}" style="width: 24px; height: 24px;" />'
            )
        return "-"

    @display(description=_("View"))
    def view_link(self, obj):
        """Link to view/edit this child category."""
        if obj.pk:
            url = reverse("admin:categories_category_change", args=[obj.pk])
            return format_html('<a href="{}">Edit</a>', url)
        return "-"


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    form = category_admin_form_factory()
    change_list_template = "admin/categories_change_list.html"
    list_filter_submit = True  # Add submit button for filters

    class Media:
        css = {"all": ("css/admin-categories.css",)}

    search_fields = ("name", "slug", "identifier")
    list_display = (
        "title",
        "symbol_img",
        "icon_img",
        # "order_display",
        # "identifier_display",
        "slug",
        "children_count",
        "parent_display",
        "order",
        "color",
        "is_active",
    )

    list_filter = (
        "is_active",
        ("parent", AutocompleteSelectMultipleFilter),
    )

    list_editable = ("order", "color")
    list_per_page = 15
    ordering = ("-parent", "order")  # Order by parent (NULL first, then by parent ID)

    actions = ["auto_set_color_from_svg"]

    # Add autocomplete for parent field to make selection easier with many categories
    autocomplete_fields = (
        "parent",
        "default",
        "symbol_detailed",
        "symbol_simple",
        "symbol_mono",
    )

    readonly_fields = ("identifier", "name_i18n", "description_i18n")

    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("slug", "identifier", "is_active"),
                    "name_i18n",
                    ("parent", "default", "order"),
                    "description_i18n",
                )
            },
        ),
        (
            _("Color"),
            {"fields": ("color",)},
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [
                    tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
                ]
                + [f"description_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
        (
            _("Symbols"),
            {"fields": (("symbol_detailed", "symbol_simple", "symbol_mono"),)},
        ),
        (
            _("Additional Data"),
            {
                "classes": ["collapse"],
                "fields": ("extra",),
                "description": _(
                    "Additional metadata as JSON. Example: {'mapcomplete_theme': 'transit'}"
                ),
            },
        ),
    )

    inlines = (ChildCategoryInline,)

    # Add custom views for symbol management
    def get_urls(self):
        """Add custom URL for symbols view."""
        from django.urls import path

        urls = super().get_urls()
        custom_urls = [
            path(
                "symbols/",
                self.admin_site.admin_view(self.symbols_view),
                name="categories_category_symbols",
            ),
        ]
        return custom_urls + urls

    def symbols_view(self, request):
        """Display all symbols grouped by slug with their three style variants."""
        from server.apps.symbols.models import Symbol
        from django.template.response import TemplateResponse

        # Get all unique slugs
        slugs = (
            Symbol.objects.values("slug")
            .order_by("slug")
            .distinct()
            .values_list("slug", flat=True)
        )

        # Build symbol groups
        symbol_groups = []
        for slug in slugs:
            symbols = Symbol.objects.filter(slug=slug).order_by("style")
            group = {"slug": slug, "symbols": {}}

            for symbol in symbols:
                group["symbols"][symbol.style] = symbol

            # Count categories using this symbol
            group["category_count"] = (
                Category.objects.filter(
                    Q(symbol_detailed__slug=slug)
                    | Q(symbol_simple__slug=slug)
                    | Q(symbol_mono__slug=slug)
                )
                .distinct()
                .count()
            )

            symbol_groups.append(group)

        context = {
            **self.admin_site.each_context(request),
            "symbol_groups": symbol_groups,
            "opts": self.model._meta,
            "title": _("All Symbols by Category"),
            "has_permission": True,
        }
        return TemplateResponse(request, "admin/categories_symbols.html", context)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        """Optimize queryset with parent selection and annotate children count."""
        qs = super().get_queryset(request)
        # Use select_related for parent, default, and symbols to avoid N+1 queries
        # Annotate children count efficiently in a single query
        return qs.select_related(
            "parent",
            "default",
            "symbol_detailed",
            "symbol_simple",
            "symbol_mono",
        ).annotate(children_count_annotated=Count("children"))

    @display(
        header=True, description=_("Name and Description"), ordering=Lower("name_i18n")
    )
    def title(self, obj):
        """Display name and description."""
        level_indent = ""
        name = f"{level_indent}{obj.name_i18n}" if obj.name_i18n else obj.slug
        description = (
            f"{level_indent}{obj.description_i18n}" if obj.description_i18n else ""
        )
        # Remove avatar to avoid FileField.url access (symbols shown in other columns)
        return (name, description, "")

    @display(description=_("Symbol"))
    def symbol_img(self, obj):
        """Display detailed symbol."""
        if obj.symbol_detailed and obj.symbol_detailed.svg_file:
            return mark_safe(
                f'<img src="{obj.symbol_detailed.svg_file.url}" width="34" alt="symbol"/>'
            )
        return "-"

    @display(description=_("Mono"))
    def icon_img(self, obj):
        """Display monochrome symbol."""
        if obj.symbol_mono and obj.symbol_mono.svg_file:
            return mark_safe(
                f'<img src="{obj.symbol_mono.svg_file.url}" width="16" alt="mono"/>'
            )
        return "-"

    @display(description=_("Identifier"), ordering="identifier")
    def identifier_display(self, obj):
        """Display identifier without 'root.' prefix."""
        identifier = obj.identifier
        if identifier and identifier.startswith("root."):
            return identifier[5:]  # Remove 'root.' prefix
        return identifier

    @display(description=_("Children"), label=True)
    def children_count(self, obj):
        """Display count of children using annotated field to avoid N+1 queries."""
        # Use the annotated count from get_queryset
        count = getattr(obj, "children_count_annotated", 0)
        if count > 0:
            url = reverse("admin:categories_category_changelist")
            filter_param = f"?parent__id__exact={obj.id}"
            return format_html(
                '<a href="{}{}" style="font-size: 14px;">{}</a>',
                url,
                filter_param,
                count,
            )
        return "-"

    @display(description=_("Order"), ordering="order")
    def order_display(self, obj):
        """Display order value."""
        return mark_safe(f"<small>{obj.order}</small>")

    @display(description=_("Parent"), label=True, ordering="parent")
    def parent_display(self, obj):
        """Display parent category if exists."""
        if obj.parent:
            return obj.parent.name_i18n or obj.parent.slug
        return format_html('<span style="color: #999;">Root</span>')

    def avatar(self, url):
        """Helper to create small avatar image."""
        return mark_safe(f'<img src="{url}" width="20" alt="avatar"/>')

    @display(description=_("Auto-set color from SVG"))
    def auto_set_color_from_svg(self, request, queryset):
        """
        Admin action to automatically set color from SVG symbols.

        Extracts the dominant color from each category's symbol SVG
        and sets it as the category color.
        """
        updated_count = 0
        skipped_count = 0

        for category in queryset:
            if category.auto_set_color_from_svg(save=True):
                updated_count += 1
            else:
                skipped_count += 1

        if updated_count > 0:
            message = _(
                f"Successfully updated color for {updated_count} category(ies)."
            )
            if skipped_count > 0:
                message += _(
                    f" Skipped {skipped_count} category(ies) with no SVG or no colors."
                )
            self.message_user(request, message, level="success")
        else:
            self.message_user(
                request,
                _(
                    "No colors were updated. Make sure categories have SVG symbols with colors."
                ),
                level="warning",
            )

    auto_set_color_from_svg.short_description = _("Auto-set color from SVG symbols")
