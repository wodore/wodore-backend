import contextlib

from django.conf import settings
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny
from django.db import models

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory


## ADMIN
# HutType is now a helper class, not a model. Use Category admin instead.
# @admin.register(HutType)
class HutTypesAdmin(ModelAdmin):
    form = required_i18n_fields_form_factory("name")
    search_fields = ("name",)
    list_display = (
        "title",
        "symbol_img",
        "icon_img",
        "comfort",
        "slug",
        "show_numbers_huts",
    )
    readonly_fields = ("name_i18n", "description_i18n")
    fieldsets = (
        (
            _("Main Information"),
            {"fields": (("slug", "name_i18n", "order"), "description_i18n")},
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
            {"fields": (("symbol_detailed", "symbol_simple", "symbol_mono"),)},
        ),
    )

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request)
        return qs.annotate(
            number_huts_open=models.Count("huts_open", distinct=True),
            number_huts_closed=models.Count("huts_closed", distinct=True),
        )

    def _get_url_str(
        self, obj: "QuerySetAny", closed: bool = False, klass: str = "font-semibold"
    ) -> str:
        number = obj.number_huts_closed if closed else obj.number_huts_open
        type_id = obj.id
        help_text = "if closed" if closed else "if open"
        hut_type_str = "hut_type_closed" if closed else "hut_type_open"
        url = (
            reverse("admin:huts_hut_changelist")
            + f"?{hut_type_str}_id__exact={type_id}"
        )
        return f'<a class="{klass}" title="{help_text}" href={url}>{number}</a>'

    @display(description=_("Huts"), ordering="number_huts")
    def show_numbers_huts(self, obj: "QuerySetAny") -> str:
        open_url = self._get_url_str(obj, closed=False)
        # return mark_safe(f"{open_url}")
        closed_url = self._get_url_str(obj, closed=True, klass="")
        return mark_safe(f"{open_url} ({closed_url})")

    @display(
        header=True, description=_("Name and Description"), ordering=Lower("name_i18n")
    )
    def title(self, obj):
        return (obj.name_i18n, obj.description_i18n, self.avatar(obj.symbol_simple.url))

    @display(description=_("Symbol"))
    def symbol_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.symbol_detailed.url}" width = "34"/>')

    @display(description=_("Icon"))
    def icon_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.symbol_mono.url}" width = "16"/>')

    def avatar(self, url):  # new
        return mark_safe(f'<img src = "{url}" width = "20"/>')

    @display(description=_("Order"), ordering="order")
    def comfort(self, obj):  # new
        return mark_safe(f"<small>{obj.order}</small>")
