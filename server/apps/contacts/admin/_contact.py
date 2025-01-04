from django.conf import settings
from django.contrib import admin
from django.db.models.functions import Lower
from django.forms import Textarea
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.huts.models import Hut
from server.apps.manager.admin import ModelAdmin
from server.apps.owners.models import Owner

from ..models import Contact


## INLINES
class _ContactHutAssociationEditInline(unfold_admin.TabularInline):
    """Contact showing huts"""

    model = Hut.contact_set.through
    fields = ("hut",)  # hot to acces "hut__name"
    autocomplete_fields = ("hut",)
    extra = 0
    verbose_name = _("Hut")


class _ContactOwnerAssociationEditInline(unfold_admin.TabularInline):
    """Contact showing owner"""

    model = Owner.contacts.through
    fields = ("owner",)
    autocomplete_fields = ("owner",)
    extra = 0
    verbose_name = _("Owner")


## ADMIN
@admin.register(Contact)
class ContactAdmin(ModelAdmin):
    """Contact Admin"""

    search_fields = ("name", "email", "function__name_i18n")
    list_display = (
        "name_email",
        "function",
        "mobile_or_phone",
        "address_fmt",
        "is_active",
        "is_public",
    )
    list_filter = ("function", "is_active", "is_public")
    readonly_fields = ("note_i18n",)
    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("is_active", "is_public"),
                    ("name", "email"),
                    "function",
                    ("mobile", "phone"),
                    "url",
                    "address",
                    "note_i18n",
                )
            },
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [f"note_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
    )

    inlines = (_ContactOwnerAssociationEditInline, _ContactHutAssociationEditInline)

    def formfield_for_dbfield(self, db_field, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, **kwargs)
        if db_field.name == "address":
            attr = formfield.widget.attrs
            attr["rows"] = 3
            formfield.widget = Textarea(attrs=attr)
        # if db_field.name == "note_i18n":
        #    formfield.widget.attrs["readonly"] = True
        #    # formfield.widget.attrs["class"] = " ".join(INPUT_CLASSES_READONLY)
        #    ic(db_field)
        #    # formfield.widget = Textarea(attrs=attr)
        return formfield

    # def formfield_for_dbfield(self, db_field, request, **kwargs):
    #    # field = super().formfield_for_dbfield(db_field, request, **kwargs)
    #    if db_field.name == "address":
    #        kwargs["widget"] = Textarea
    #        # field.widget = Textarea
    #    return field

    @display(header=True, description=_("Name and Email"), ordering=Lower("name"))
    def name_email(self, obj):
        return (obj.name, obj.email)

    @display(header=True, description=_("Address"))
    def address_fmt(self, obj):
        adr_list = [a.strip() for a in obj.address.replace(",", "\n").split("\n")]
        header = ""
        if adr_list:
            header = adr_list[0]
        content = ""
        if len(adr_list) > 1:
            content = adr_list[1:]
        return header, mark_safe(", ".join(content))

    @display(header=False, description=_("Phone"))
    def mobile_or_phone(self, obj):
        mobile = self._phone_link(obj.mobile, icon="smartphone")
        phone = self._phone_link(obj.phone, icon="call")
        return mark_safe(f"{mobile}</br>{phone}")

    def _phone_link(self, number: str, icon: str | None = None) -> str:
        if icon:
            icon = f'<span class="material-symbols-outlined" style="font-size:small">{icon}</span>'
        else:
            icon = ""
        if number:
            return f"<a href=tel:{number}>{icon} {number}</a>"
        return ""
