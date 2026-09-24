# NOTE: description=_(...) is the project-wide lazy-gettext idiom (i18n-safe);  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
# per-line pyright ignores below suppress the unfold-stub str-typing mismatch.
import contextlib
from typing import ClassVar

with contextlib.suppress(ModuleNotFoundError):
    from django_stubs_ext import QuerySetAny


from django_admin_runner.admin import CommandRunnerModelAdminMixin

from django.conf import settings
from django.contrib import admin
from django.contrib.postgres.aggregates import JSONBAgg
from django.db.models.functions import JSONObject, Lower
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold.contrib.filters.admin import (
    AutocompleteSelectMultipleFilter,
    BooleanRadioFilter,
    ChoicesCheckboxFilter,
)
from unfold.decorators import action, display

from server.apps.images.transfomer import ImagorImage
from server.apps.manager.admin import ModelAdmin, RelatedOnlyCheckboxFilter
from server.apps.organizations.models import Organization
from server.apps.translations.admin_helpers import (
    DescriptionQualityFilter,
    LLMAdminMixin,
)
from server.apps.translations.forms import required_i18n_fields_form_factory

from ..forms import HutAdminFieldsets
from ..models import Hut, HutTypeHelper
from ..widgets import OpenMonthlyWidget
from ._associations import (
    HutContactAssociationEditInline,
    HutImageAssociationEditInline,
    HutOrganizationAssociationEditInline,
    HutOrganizationAssociationViewInline,
)
from ._hut_source import HutSourceViewInline

# Import availability inline
try:
    from server.apps.availability.admin import HutAvailabilityViewInline
except ImportError:
    HutAvailabilityViewInline = None

## INLINES


## ADMIN
@admin.register(Hut)
class HutsAdmin(LLMAdminMixin, CommandRunnerModelAdminMixin, ModelAdmin):
    search_fields = ("name",)
    # list_select_related = ()  # ( "type", "owner")
    form = required_i18n_fields_form_factory("name")
    list_filter_submit = True  # Add submit button for filters
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    # list_select_related = ("org_set", "org_set__details")
    # list_select_related = ["org_set__source"]
    list_display = (
        "symbol_img",
        "hut_thumb",
        "title",
        "location_coords",
        "hut_type",
        "logo_orgs",
        "is_public",
        "is_modified",
        "is_active",
        "review_tag",
        "description_quality_display",
        "view_link",
    )
    list_display_links = ("symbol_img", "hut_thumb", "title")
    list_filter = (
        ("is_active", BooleanRadioFilter),
        ("is_public", BooleanRadioFilter),
        ("is_modified", BooleanRadioFilter),
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
        DescriptionQualityFilter,
        (
            "hut_type_open",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by hut type open with autocomplete
        (
            "hut_type_closed",
            AutocompleteSelectMultipleFilter,
        ),  # Filter by hut type closed with autocomplete
        (
            "org_set",
            RelatedOnlyCheckboxFilter,
        ),  # Filter by sources (checkboxes, only orgs linked to huts)
    )
    fieldsets = HutAdminFieldsets
    autocomplete_fields = ("hut_owner", "hut_type_open", "hut_type_closed")
    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "note_i18n",
        "hut_images",
        "created",
        "modified",
    )
    list_per_page = 50

    def get_inlines(self, request, obj):
        """Dynamically add availability inline if app is installed"""
        inlines = [
            HutImageAssociationEditInline,
            HutContactAssociationEditInline,
            HutOrganizationAssociationViewInline,
            HutOrganizationAssociationEditInline,
            HutSourceViewInline,
        ]
        if HutAvailabilityViewInline is not None:
            inlines.append(HutAvailabilityViewInline)
        return inlines

    def formfield_for_dbfield(  # pyright: ignore[reportIncompatibleMethodOverride]  # untyped django_admin_runner base in MRO
        self, db_field, request, **kwargs
    ):
        """Customize FK querysets and the `open_monthly` widget.

        The plain Category/Organization querysets contain thousands of OSM
        brand entries — rendering them as selects slows the change page down
        for seconds (9k+ options with symbol joins)."""
        if db_field.name == "open_monthly":
            kwargs["widget"] = OpenMonthlyWidget()
        elif db_field.name in ("hut_type_open", "hut_type_closed"):
            # hut types only (accommodation subtree), not all categories
            kwargs["queryset"] = HutTypeHelper.get_queryset()
        elif db_field.name == "availability_source_ref":
            # only organizations whose service provides booking data
            booking = [
                slug
                for slug, service in settings.SERVICES.items()
                if service.support_booking
            ]
            kwargs["queryset"] = Organization.objects.filter(
                slug__in=booking, is_active=True
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_queryset(self, request: HttpRequest) -> "QuerySetAny":
        qs = super().get_queryset(request).prefetch_related("image_set")
        # prefetch_related("orgs_source", "orgs_source__organization").
        return qs.select_related(
            "hut_type_open", "hut_type_closed", "hut_owner"
        ).annotate(
            orgs=JSONBAgg(
                JSONObject(
                    logo="org_set__logo",
                    name_i18n="org_set__name_i18n",
                    link_i18n="orgs_source__link",
                )
            ),
        )

    @display(
        description=_("Status"),  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
        ordering="status",
        label={
            Hut.ReviewStatusChoices.review: "info",
            Hut.ReviewStatusChoices.done: "success",
            Hut.ReviewStatusChoices.new: "warning",  # green
            Hut.ReviewStatusChoices.rework: "danger",
        },
    )
    def review_tag(self, obj):
        return obj.review_status

    @display(header=True, ordering=Lower("name"))
    def title(self, obj):
        # if obj.hut_owner:
        #    owner = textwrap.shorten(obj.hut_owner.name, width=30, placeholder="...")
        # else:
        #    owner = "-"
        return (obj.name_i18n, obj.slug)  # self.icon_thumb(obj.type.icon_simple.url))

    @display(header=True, description=_("Type"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def hut_type(self, obj):
        opened = mark_safe(f'<span class = "text-xs">{obj.hut_type_open.slug}</span>')
        closed = mark_safe(
            f'<span class = "text-xs">{obj.hut_type_closed.slug if obj.hut_type_closed else "-"}</span>'
        )
        return (opened, closed)

    @display(header=True, description=_("Location"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def location_coords(self, obj):
        return (
            f"{obj.location.y:.3f}/{obj.location.x:.3f}",
            f"{obj.elevation}m" if obj.elevation else "-",
        )

    @display(description="")
    def symbol_img(self, obj):  # new
        if (
            obj.hut_type_open.symbol_detailed
            and obj.hut_type_open.symbol_detailed.svg_file
        ):
            return mark_safe(
                f'<img src="{obj.hut_type_open.symbol_detailed.svg_file.url}" width="50px"/>'
            )
        return "-"

    @display(description=_("Sources"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def logo_orgs(self, obj: Hut) -> str:  # new
        SRC = settings.MEDIA_URL
        imgs = [
            f'<a href={o["link_i18n"]} target="blank"><img class="inline pr-2" src="{SRC}/{o["logo"]}" width="24px" alt="{o["name_i18n"]}"/></a>'
            for o in obj.orgs  # pyright: ignore[reportAttributeAccessIssue]  # JSONBAgg annotation
        ]

        # return ", ".join([str(o.organization.name + o.link_i18n) for o in obj.orgs.all()])
        return mark_safe(f"<span>{''.join(imgs)}</span>")

    @display(description="")
    def view_link(self, obj: Hut) -> str:
        url = f"{settings.FRONTEND_DOMAIN}/hut/{obj.slug}#12/{obj.location.y}/{obj.location.x}"
        view = f'<span><a class="text-sm" href="{url}" target="_blank"> <span class="material-symbols-outlined"> visibility </span> </a>'
        if obj.is_public and obj.is_active:
            return mark_safe(view)
        if not obj.is_public and obj.is_active:
            return mark_safe(
                '<span class="material-symbols-outlined"> visibility_off </span>'
            )
        return mark_safe(
            '<span class="material-symbols-outlined"> disabled_visible </span>'
        )

    @display(description=_("Photos"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def hut_images(self, obj):  # new
        img_html = "<div>"
        for i, img in enumerate(
            obj.image_set.select_related("source_org", "license")
            .order_by("details__order")
            .all()
        ):
            link = reverse("admin:images_image_change", args=[img.pk])
            img_tag = f"""
              <a href='{link}' target='_blank'>{img.get_image_tag(radius=10, height=120, width=200)}</a>
            """
            lic = f"""{img.license.name_i18n}"""
            public_private_tag = (
                "<b style='color:red'>Private</b>"
                if img.license.no_publication
                else "<i style='color:orange'>Public</i>"
            )
            author_source = []
            if img.author and img.author_url:
                author_source.append(
                    f"<i><a href='{img.author_url}'>{img.author}</a></i>"
                )
            elif img.author:
                author_source.append(f"<i>{img.author}</i>")
            if img.source_org:
                author_source.append(
                    f"""
                                    <div style='display:inline-block'>
                                      <img style='display:inline-block' src='{img.source_org.logo.url}' width='16'>
                                      {img.source_org.name_i18n}
                                      </img>
                                    </div>
                                      """
                )
            # print(img.details.order)
            img_info = f"""
              <span class="text-xs">{public_private_tag}</span>
              <h2><b>#{i + 1} - {img.caption_i18n}</b></h2>
              Status: <i>{img.review_status}</i><br/>
              {", ".join(author_source)}<br/>
              <small>{lic}</small><br/>
            <span><a class="text-xs" href="{img.image.url}" target='_blank'> <span class="material-symbols-outlined"> visibility </span> </a>
            <span><a class="text-xs" href="{link}" target='_blank'> <span class="material-symbols-outlined"> edit </span> </a>
            """
            img_html += f"""<div style="padding:5px;">
                              <div style='display:inline-block; padding-right:10px'>
                                {img_tag}
                              </div>
                              <div style='display:inline-block'>
                                {img_info}
                              </div>
                            </div>"""
        img_html += "</div>"
        return mark_safe(img_html)

    @display(description=_("Photo"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def hut_thumb(self, obj):  # new
        if obj.photos:  # old style, show if available
            return (
                ImagorImage(obj.photos)
                .transform(round_corner=(15), size="50x50")
                .get_html()
            )

        img = obj.image_set.order_by("details__order").first()
        if img:
            return img.get_image_tag(radius=15, height=50, width=50)
        return ""

    ## ACTIONS
    actions_row = (
        "action_row_set_review_to_done",
        "action_row_set_review_to_review",
        "action_row_set_inactive",
        "action_row_delete",
    )
    actions_detail = ("action_detail_prev", "action_detail_next")

    ## TODO: check if form is saved, save form and show next (or tell them to save)
    @action(description=_("Next"), permissions=["view"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_detail_next(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        return redirect(
            reverse_lazy("admin:huts_hut_change", args=(obj.next() or object_id,))  # pyright: ignore[reportArgumentType]  # lazy URL
        )

    @action(description=_("Previous"), permissions=["view"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_detail_prev(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        return redirect(
            reverse_lazy("admin:huts_hut_change", args=(obj.prev() or object_id,))  # pyright: ignore[reportArgumentType]  # lazy URL
        )

    @action(description=_(mark_safe("set to <b>done</b>")), permissions=["change"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_set_review_to_done(
        self, request: HttpRequest, object_id: int
    ):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.done
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(description=_(mark_safe("set to <b>review</b>")), permissions=["change"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_set_review_to_review(
        self, request: HttpRequest, object_id: int
    ):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.review
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(
        description=_(mark_safe("set to <b>reject</b> (inactive)")),  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
        permissions=["delete"],
    )
    def action_row_set_inactive(
        self, request: HttpRequest, object_id: int
    ):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.review_status = Hut.ReviewStatusChoices.reject
        obj.is_active = False
        obj.save()
        return redirect(request.META.get("HTTP_REFERER"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(description=_(mark_safe("<b>delete</b> entry")), permissions=["delete"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_delete(self, request: HttpRequest, object_id: int):  # obj: Hut):
        obj = Hut.objects.get(id=object_id)
        obj.delete()
        return redirect(request.META.get("HTTP_REFERER"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
