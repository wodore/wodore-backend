"""Unfold admin for the environment variable registry."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin

from .models import EnvVar


@admin.register(EnvVar)
class EnvVarAdmin(ModelAdmin):
    """Registry admin — values are masked in the list view."""

    list_display = ("name", "masked_value", "env_fallback", "is_active", "description")
    list_filter = ("is_active", "env_fallback")
    search_fields = ("name", "description")
    ordering = ("name",)

    @display(description="Value")
    def masked_value(self, obj: EnvVar, _request: HttpRequest | None = None) -> str:
        if not obj.value:
            if not obj.env_fallback:
                return "∅ pinned empty"
            return "— env fallback"
        tail = obj.value[-4:]
        return f"••••{tail}" if len(obj.value) > 4 else "••••"
