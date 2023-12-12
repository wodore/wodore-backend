from typing import ClassVar

from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..forms import HutAdminFieldsets
from ..models import (
    Hut,
)
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
    list_select_related = (
        "type",
        "owner",
    )
    form = required_i18n_fields_form_factory("name")
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    # list_select_related = ("organizations", "organizations__details")
    # list_select_related = ["organizations__source"]
    list_display = ("symbol_img", "title", "location", "elevation", "type", "logo_orgs", "is_active", "review_tag")
    list_display_links = ("symbol_img", "title")
    fieldsets = HutAdminFieldsets
    autocomplete_fields = ("owner",)
    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "note_i18n",
        "created",
        "modified",
    )
    list_per_page = 100

    inlines = (
        HutContactAssociationEditInline,
        HutOrganizationAssociationViewInline,
        HutOrganizationAssociationEditInline,
        HutSourceViewInline,
    )

    ## TODO: does not work yet
    # def get_queryset(self, request):
    #    qs = super().get_queryset(request)
    #    return qs.prefetch_related(
    #        models.Prefetch("organizations", queryset=HutOrganizationAssociation.objects.all(), to_attr="source")
    #    )

    @display(
        description=_("Status"),
        ordering="status",
        label={Hut.ReviewStatusChoices.review: "info", Hut.ReviewStatusChoices.done: "success"},
    )
    def review_tag(self, obj):
        return obj.review_status

    @display(header=True)
    def title(self, obj):
        return (obj.name_i18n, obj.owner)  # self.icon_thumb(obj.type.icon_simple.url))

    def location(self, obj):
        return f"{obj.point.y:.4f}, {obj.point.x:.4f}"

    @display(description="")
    def symbol_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.type.symbol.url}" width = "38"/>')

    @display(description=_("Organizations"))
    def logo_orgs(self, obj):  # new
        # orgs = [o for o in obj.organizations.all()]
        # imgs = [
        #    f'<a href={o.link} target="blank"><img class="inline pr-2" src="{o.logo}" width="28" alt="{o.name}"/></a>'
        #    for o in obj.view_organizations()
        # ]
        imgs = [
            f'<a href={o.source.first().link_i18n} target="blank"><img class="inline pr-2" src="{o.logo.url}" width="28" alt="{o.name_i18n}"/></a>'
            for o in obj.organizations.all()
        ]

        return mark_safe(f'<span>{"".join(imgs)}</span>')
