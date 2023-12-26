import textwrap
from typing import ClassVar

from django_stubs_ext import QuerySetAny

from django.conf import settings
from django.contrib import admin
from django.contrib.postgres.aggregates import JSONBAgg
from django.db import models
from django.db.models.functions import JSONObject, Lower
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import action, display

from server.apps import organizations
from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory
from server.core.utils import text_shorten_html

from ..forms import HutAdminFieldsets
from ..models import Hut, HutOrganizationAssociation
from ._associations import (
    HutContactAssociationEditInline,
    HutOrganizationAssociationEditInline,
    HutOrganizationAssociationViewInline,
)
from ._hut_source import HutSourceViewInline

## INLINES


## ADMIN
@admin.register(Hut)
class HutsAdmin(ModelAdmin):
    search_fields = ("name",)
    # list_select_related = ()  # ( "type", "owner")
    form = required_i18n_fields_form_factory("name")
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    # list_select_related = ("org_set", "org_set__details")
    # list_select_related = ["org_set__source"]
    list_display = (
        "symbol_img",
        "title",
        "location_coords",
        "elevation",
        "hut_type",
        "logo_orgs",
        "is_active",
        "is_public",
        "review_tag",
    )
    list_display_links = ("symbol_img", "title")
    list_filter = ("is_active", "is_public", "hut_type_open", "org_set")
    fieldsets = HutAdminFieldsets
    autocomplete_fields = ("hut_owner",)
    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "note_i18n",
        "created",
        "modified",
    )
    list_per_page = 50

    inlines = (
        HutContactAssociationEditInline,
        HutOrganizationAssociationViewInline,
        HutOrganizationAssociationEditInline,
        HutSourceViewInline,
    )

    def get_queryset(self, request: HttpRequest) -> QuerySetAny:
        qs = super().get_queryset(request)
        # prefetch_related("orgs_source", "orgs_source__organization").
        return qs.select_related("hut_type_open", "hut_owner").annotate(
            orgs=JSONBAgg(
                JSONObject(
                    logo="org_set__logo",
                    name_i18n="org_set__name_i18n",
                    link_i18n="orgs_source__link",
                )
            ),
        )

    @display(
        description=_("Status"),
        ordering="status",
        label={
            Hut.ReviewStatusChoices.review: "info",
            Hut.ReviewStatusChoices.done: "success",
            Hut.ReviewStatusChoices.research: "warning",
        },
    )
    def review_tag(self, obj):
        return obj.review_status

    @display(header=True, ordering=Lower("name"))
    def title(self, obj):
        if obj.hut_owner:
            owner = textwrap.shorten(obj.hut_owner.name, width=30, placeholder="...")
        else:
            owner = "-"
        return (obj.name_i18n,)  # self.icon_thumb(obj.type.icon_simple.url))

    @display(header=True, ordering=Lower("hut_type_open"))
    def hut_type(self, obj):
        opened = mark_safe(f'<span class = "text-xs">{obj.hut_type_open.slug}</span>')
        closed = mark_safe(f'<span class = "text-xs">{obj.hut_type_closed.slug if obj.hut_type_closed else "-"}</span>')
        return (opened, closed)

    def location_coords(self, obj):
        return f"{obj.location.y:.4f}, {obj.location.x:.4f}"

    @display(description="")
    def symbol_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.hut_type_open.symbol.url}" width = "38"/>')

    @display(description=_("Organizations"))
    def logo_orgs(self, obj: Hut) -> str:  # new
        SRC = settings.MEDIA_URL
        imgs = [
            f'<a href={o["link_i18n"]} target="blank"><img class="inline pr-2" src="{SRC}/{o["logo"]}" width="28" alt="{o["name_i18n"]}"/></a>'
            for o in obj.orgs
        ]

        # return ", ".join([str(o.organization.name + o.link_i18n) for o in obj.orgs.all()])
        return mark_safe(f'<span>{"".join(imgs)}</span>')

    ## ACTIONS
    actions_row = (
        "action_row_set_review_to_done",
        "action_row_set_review_to_review",
        "action_row_set_inactive",
        "action_row_delete",
    )
    actions_detail = ("action_detail_prev", "action_detail_next")

    ## TODO: check if form is saved, save form and show next (or tell them to save)
    @action(description=_("Next"), permissions=["view"])
    def action_detail_next(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        return redirect(reverse_lazy("admin:huts_hut_change", args=(obj.next() or object_id,)))

    @action(description=_("Previous"), permissions=["view"])
    def action_detail_prev(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        return redirect(reverse_lazy("admin:huts_hut_change", args=(obj.prev() or object_id,)))

    @action(description=_(mark_safe("set to <b>done</b>")), permissions=["change"])
    def action_row_set_review_to_done(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.done
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))

    @action(description=_(mark_safe("set to <b>review</b>")), permissions=["change"])
    def action_row_set_review_to_review(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.review
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))

    @action(description=_(mark_safe("set to <b>reject</b> (inactive)")), permissions=["delete"])
    def action_row_set_inactive(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.reject
        obj.is_active = False
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))

    @action(description=_(mark_safe("<b>delete</b> entry")), permissions=["delete"])
    def action_row_delete(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.delete()
        return redirect(request.META.get("HTTP_REFERER"))
