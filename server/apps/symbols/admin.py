# Models
import contextlib
from typing import ClassVar

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from django.contrib import admin
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .forms import SymbolAdminFieldsets
from .models import Symbol


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
        "review_status",
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
        if not obj.uploaded_by_user:
            obj.uploaded_by_user = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.select_related("license", "source_org", "uploaded_by_user")

    @display(description=_("SVG"))
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

    @display(description=_("Preview"))
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

    @display(description=_("Search Text"))
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

    @display(description=_("License"), header=True)
    def license_display(self, obj):
        """Show license with link."""
        if obj.license:
            link = mark_safe(
                f'<a href="{obj.license.link_i18n}" target="_blank">{obj.license.name_i18n}</a>'
            )
            return link, link
        return mark_safe("-"), mark_safe("-")

    @display(description=_("Source"), header=True)
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

    @display(description=_("Status"))
    def review_status_display(self, obj):
        """Show review status."""
        return obj.get_review_status_display()


# TODO: Add SymbolTagAdmin if tags are implemented in the future
# @admin.register(SymbolTag)
# class SymbolTagAdmin(ModelAdmin):
#     """Admin panel for SymbolTag model."""
#     pass
