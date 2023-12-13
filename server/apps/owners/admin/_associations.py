from typing import ClassVar

from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.huts.admin import HutSourceViewInline
from server.apps.huts.models import Hut
from server.apps.manager.admin import ModelAdmin

from ..models._associations import OwnerContactAssociation, OwnerHutProxy


## ADMIN
@admin.register(OwnerContactAssociation)
class OwnerContactAssociationsAdmin(ModelAdmin):
    search_fields = ("owner__name_i18n",)
    list_display = ("owner", "contact", "order", "is_active", "is_public")  # , "contact__is_active")
    list_filter = ("contact__is_active", "contact__is_public")  # , "owner")
    fields = ("owner", "contact", "order")

    @display(boolean=True)
    def is_active(self, obj):
        return obj.contact.is_active

    @display(boolean=True)
    def is_public(self, obj):
        return obj.contact.is_public


## ADMIN
@admin.register(OwnerHutProxy)
class OwnerHutAssociationsAdmin(ModelAdmin):
    search_fields = ("owner__name_i18n",)
    list_display = (
        "slug_small",
        "owner_title",
        "hut_title",
        "is_active",
        "review_tag",
    )
    list_filter = ("is_active", "review_status")  # , "owner")
    readonly_fields = ("name_i18n",)
    fields = ("name_i18n", "owner", "review_status", "review_comment")
    autocomplete_fields = ("owner",)
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    inlines = (HutSourceViewInline,)

    @display(description=_("Slug"))
    def slug_small(self, obj):  # new
        return mark_safe(f'<span class="text-gray-500">{obj.slug}</span>')

    @display(description=_("Owner"), header=True)
    def owner_title(self, obj):  # new
        return (
            obj.owner.name_i18n,
            mark_safe(f'<a href="{obj.owner.url}" target="_blank">{obj.owner.url}</a>'),
        )  # , mark_safe(f'<img src = "{obj.type.symbol_simple.url}" width = "24"/>')

    @display(description=_("Hut"), header=True)
    def hut_title(self, obj):  # new
        return obj.name_i18n, obj.type.name_i18n, mark_safe(f'<img src = "{obj.type.symbol_simple.url}" width = "24"/>')

    @display(
        description=_("Status"),
        ordering="status",
        label={Hut.ReviewStatusChoices.review: "info", Hut.ReviewStatusChoices.done: "success"},
    )
    def review_tag(self, obj):
        return obj.review_status
