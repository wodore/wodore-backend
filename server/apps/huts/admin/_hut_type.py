from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import QuerySetAny
from django.db import models

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..models import (
    HutType,
)


## ADMIN
@admin.register(HutType)
class HutTypesAdmin(ModelAdmin):
    form = required_i18n_fields_form_factory("name")
    search_fields = ("name",)
    list_display = ("title", "symbol_img", "icon_img", "comfort", "slug", "show_numbers_huts")
    readonly_fields = ("name_i18n", "description_i18n")
    fieldsets = (
        (
            _("Main Information"),
            {"fields": (("slug", "name_i18n", "level"), "description_i18n")},
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
            _("Symbols & Icon"),
            {"fields": (("symbol", "symbol_simple", "icon"),)},
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySetAny:
        qs = super().get_queryset(request)
        return qs.annotate(number_huts=models.Count("huts"))

    @display(description=_("Huts"), ordering="number_huts")
    def show_numbers_huts(self, obj):
        url = reverse("admin:huts_hut_changelist") + f"?type__id__exact={obj.id}"
        return mark_safe(f'<a class="font-semibold" href={url}>{obj.number_huts}</a>')

    @display(header=True, description=_("Name and Description"), ordering=Lower("name_i18n"))
    def title(self, obj):
        return (obj.name_i18n, obj.description_i18n, self.avatar(obj.symbol_simple.url))

    @display(description=_("Symbol"))
    def symbol_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.symbol.url}" width = "34"/>')

    @display(description=_("Icon"))
    def icon_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.icon.url}" width = "16"/>')

    def avatar(self, url):  # new
        return mark_safe(f'<img src = "{url}" width = "20"/>')

    @display(description=_("Level"), ordering="level")
    def comfort(self, obj):  # new
        return mark_safe(f"<small>{obj.level}</small>")
