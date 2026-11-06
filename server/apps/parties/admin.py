import contextlib
from typing import override

from django.conf import settings
from django.contrib import admin
from django.db import models
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from .models import Party, PartyLink


## INLINES
class _PartyLinksInline(unfold_admin.TabularInline):
    """Party showing external links"""

    model = PartyLink
    fields = ("external_link", "order")
    autocomplete_fields = ("external_link",)
    extra = 0
    verbose_name = _("Link")


## ADMIN
@admin.register(Party)
class PartyAdmin(ModelAdmin):
    """Party Admin"""

    form = required_i18n_fields_form_factory("name")

    search_fields = ("slug", "name", "name_de")
    list_display = (
        "name_slug",
        "is_active",
        "is_public",
        "review_status",
        "show_numbers_links",
    )
    list_filter = ("is_active", "is_public", "review_status")
    autocomplete_fields = ("symbol_color", "symbol_mono")

    inlines = (_PartyLinksInline,)

    fieldsets = [
        (
            _("Main Information"),
            {
                "fields": (
                    ("slug", "name_i18n"),
                    ("is_active", "is_public"),
                    "review_status",
                    ("symbol_color", "symbol_mono"),
                    "note_i18n",
                )
            },
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [f"name_{code}" for code in settings.LANGUAGE_CODES]
                + [f"note_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
    ]

    @override
    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.annotate(number_links=models.Count("link_associations"))

    @display(description=_("Links"), ordering="number_links")
    def show_numbers_links(self, obj: Party):
        return getattr(obj, "number_links", 0)

    @display(header=True, description=_("Name"), ordering=Lower("name_i18n"))
    def name_slug(self, obj: Party):
        return obj.name_i18n, obj.slug


@admin.register(PartyLink)
class PartyLinkAdmin(ModelAdmin):
    """Party Link association admin (mirrors the owners association admins)"""

    search_fields = ("party__slug", "party__name", "external_link__url")
    list_display = ("party", "external_link", "order")
    list_select_related = ("party", "external_link")
    autocomplete_fields = ("party", "external_link")
