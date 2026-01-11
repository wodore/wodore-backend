import contextlib

from django.conf import settings
from django.contrib import admin
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from .models import Category


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    form = required_i18n_fields_form_factory("name")

    search_fields = ("name", "slug")
    list_display = (
        "title",
        "symbol_img",
        "icon_img",
        # "order_display",
        "slug",
        "parent_display",
        "order",
        "is_active",
        # "parent",
    )

    list_filter = (
        "is_active",
        "parent",
    )

    list_editable = ("is_active", "order")  # , "parent")
    search_fields = ("name", "slug")

    readonly_fields = ("name_i18n", "description_i18n")

    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("slug", "name_i18n", "is_active"),
                    ("parent", "default", "order"),
                    "description_i18n",
                )
            },
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
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        """Optimize queryset with parent selection."""
        qs = super().get_queryset(request)
        return qs.select_related("parent", "default")

    @display(
        header=True, description=_("Name and Description"), ordering=Lower("name_i18n")
    )
    def title(self, obj):
        """Display name, description, and small symbol."""
        level_indent = "　" * obj.get_level()  # Japanese space for indentation
        name = f"{level_indent}{obj.name_i18n}" if obj.name_i18n else obj.slug
        description = (
            f"{level_indent}{obj.description_i18n}" if obj.description_i18n else ""
        )
        avatar = self.avatar(obj.symbol_simple.url) if obj.symbol_simple else ""
        return (name, description, avatar)

    @display(description=_("Symbol"))
    def symbol_img(self, obj):
        """Display detailed symbol."""
        if obj.symbol_detailed:
            return mark_safe(
                f'<img src="{obj.symbol_detailed.url}" width="34" alt="symbol"/>'
            )
        return "-"

    @display(description=_("Mono"))
    def icon_img(self, obj):
        """Display monochrome symbol."""
        if obj.symbol_mono:
            return mark_safe(
                f'<img src="{obj.symbol_mono.url}" width="16" alt="mono"/>'
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
