import textwrap

from django.conf import settings
from django.contrib import admin
from django.db.models.functions import Lower
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.huts.models import Hut
from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory
from server.core.utils import text_shorten_html

from ..models import Owner


## INLINES
class _OwnerShowContactsEditInline(unfold_admin.TabularInline):
    """Owner showing contacts"""

    model = Owner.contacts.through
    fields = ("contact",)  # how to to acces "hut__name", probably custom from
    autocomplete_fields = ("contact",)
    extra = 0
    verbose_name = _("Contacts")


class _OwnerShowHutsViewInline(unfold_admin.TabularInline):
    """Owner showing huts"""

    model = Hut
    fields = ("slug", "name_i18n", "url", "type")
    # autocomplete_fields = ("name", "slug")
    extra = 0
    can_delete = False
    verbose_name = _("Hut")
    show_change_link = True

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


## ADMIN
@admin.register(Owner)
class OwnerAdmin(ModelAdmin):
    """Owner Admin"""

    form = required_i18n_fields_form_factory("name")

    search_fields = ("name",)
    list_display = ("name_slug", "url", "note_short")

    inlines = (
        _OwnerShowContactsEditInline,
        _OwnerShowHutsViewInline,
    )
    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("slug", "name_i18n"),
                    "url",
                    "note_i18n",
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
                + [f"note_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
    )

    @display(header=True, description=_("Name"), ordering=Lower("name_i18n"))
    def name_slug(self, obj):  # new
        return obj.name_i18n, obj.slug

    @display(description=_("Note"))
    def note_short(self, obj):  # new
        return text_shorten_html(obj.note_i18n, width=100)
