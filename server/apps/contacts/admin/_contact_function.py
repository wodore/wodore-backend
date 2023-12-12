from django.conf import settings
from django.contrib import admin

# from django.utils.safestring import mark_safe
# from unfold.decorators import display
from django.utils.translation import gettext_lazy as _

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..models import ContactFunction


## ADMIN
@admin.register(ContactFunction)
class ContactFunctionAdmin(ModelAdmin):
    """Contact Functions Admin"""

    form = required_i18n_fields_form_factory("name")
    search_fields = ("name",)
    list_display = ("slug", "name_i18n", "priority")
    readonly_fields = ("name_i18n",)
    fieldsets = (
        (
            _("Main Information"),
            {"fields": (("slug", "priority"), "name_i18n", "symbol")},
        ),
        (
            _("Translations"),
            {
                "classes": ("collapse",),
                "fields": [f"name_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
    )
