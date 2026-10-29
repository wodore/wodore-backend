from typing import ClassVar

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.huts.admin import HutSourceViewInline
from server.apps.huts.models import Hut
from server.apps.manager.admin import ModelAdmin

from ..models._associations import OwnerContactAssociation
from ..models._owner import Owner
from ..models._owner_hut_proxy import OwnerHutProxy


## ADMIN
@admin.register(OwnerContactAssociation)
class OwnerContactAssociationsAdmin(ModelAdmin):
    search_fields = ("owner__name_i18n",)
    list_display = (
        "owner",
        "contact",
        "order",
        "is_active",
        "is_public",
    )  # , "contact__is_active")
    list_filter = ("contact__is_active", "contact__is_public")  # , "owner")
    fields = ("owner", "contact", "order")
    list_select_related = ("contact",)

    @display(boolean=True)
    def is_active(self, obj: OwnerContactAssociation) -> bool:
        return obj.contact.is_active

    @display(boolean=True)
    def is_public(self, obj: OwnerContactAssociation) -> bool:
        return obj.contact.is_public


## ADMIN
@admin.register(OwnerHutProxy)
class OwnerHutAssociationsAdmin(ModelAdmin):
    search_fields = ("hut_owner__name_i18n",)
    list_display = (
        "slug_small",
        "owner_title",
        "hut_title",
        "is_active",
        "review_tag",
    )
    list_filter = ("is_active",)  # , "owner")
    readonly_fields = ("name_i18n",)
    fields = ("name_i18n", "hut_owner", "review_status", "review_comment")
    autocomplete_fields = ("hut_owner",)
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    inlines = (HutSourceViewInline,)
    list_select_related = ("hut_type_open",)

    @display(description=_("Slug"))
    def slug_small(self, obj: OwnerHutProxy) -> SafeString:  # new
        return format_html('<span class="text-gray-500">{}</span>', obj.slug)

    @display(description=_("Owner"), header=True)
    def owner_title(self, obj: OwnerHutProxy) -> tuple[str, str]:  # new
        owner: Owner | None = obj.hut_owner  # FK string-ref: plugin-less inference gap
        if owner:
            return (
                owner.name_i18n,
                format_html(
                    '<a href="{}" target="_blank">{}</a>', owner.url, owner.url
                ),
            )  # , mark_safe(f'<img src = "{obj.type.symbol_primitive.url}" width = "24"/>')
        return ("-", "")

    @display(description=_("Hut"), header=True)
    def hut_title(self, obj: OwnerHutProxy) -> tuple[str, str, SafeString]:  # new
        return (
            obj.name_i18n,
            obj.hut_type_open.name_i18n,
            format_html(
                # latent bug kept as-is (typing ratchet must not change runtime
                # behavior): Symbol has no `url` attribute, so this raises
                # AttributeError whenever the column renders — models live
                # outside this app and are out of ratchet scope.
                '<img src = "{}" width = "24"/>',
                obj.hut_type_open.symbol_primitive.url,  # type: ignore  # latent AttributeError: Symbol has no `url` attr (string-ref FK, models out of scope)
            ),
        )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            Hut.ReviewStatusChoices.review: "info",
            Hut.ReviewStatusChoices.done: "success",
        },
    )
    def review_tag(self, obj: OwnerHutProxy) -> str:
        return obj.review_status
