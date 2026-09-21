# NOTE: description=_(...) is the project-wide lazy-gettext idiom (i18n-safe);  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
# per-line pyright ignores below suppress the unfold-stub str-typing mismatch.
from typing import ClassVar

from django.contrib import admin
from django.db import models
from django.http import HttpRequest
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin
from unfold.contrib.filters.admin import BooleanRadioFilter, ChoicesCheckboxFilter
from unfold.decorators import action, display

from server.apps.manager.admin import ModelAdmin, RelatedOnlyCheckboxFilter
from server.apps.manager.widgets import UnfoldReadonlyJSONSuit
from server.core.utils import text_shorten_html

from ..models import (
    HutSource,
)


## INLINES
class HutSourceViewInline(unfold_admin.StackedInline):
    tab = True
    model = HutSource
    readonly_fields = (
        "created",
        "modified",
        "organization",
        "source_id",
        "name",
    )  # , "source_data"] # TODO formated json
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    fields = (
        ("organization", "source_id"),
        ("review_status"),
        ("review_comment"),
        "source_data",
        "is_active",
    )
    extra = 0
    max_num = 20
    show_change_link = True
    can_delete = False
    autocomplete_fields = ("organization",)  # ~680 orgs (OSM brands): no plain select
    # classes = ("collapse",)  # Commented out to keep tab expanded by default
    formfield_overrides: ClassVar = {
        models.JSONField: {"widget": UnfoldReadonlyJSONSuit}
    }

    def has_add_permission(self, request, obj):
        return False


## ADMIN
@admin.register(HutSource)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
# class HutsSourceAdmin(ModelAdmin[HutSource]):
class HutsSourceAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    # view_on_site = True
    # list_select_related = True
    list_display = (
        "name",
        "organization",
        "review_comment_short",
        "is_active",
        "is_current",
        "version",
        "review_tag",
    )
    list_filter_submit = True  # Add submit button for filters
    list_filter = (
        ("organization", RelatedOnlyCheckboxFilter),  # checkboxes, only orgs in use
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
        ("is_active", BooleanRadioFilter),
        ("is_current", BooleanRadioFilter),
        "version",
    )
    list_display_links = ("name",)
    search_fields = ("name",)
    sortable_by = ("name", "organization")
    readonly_fields = ("created", "modified", "organization", "source_id", "name")
    fields = (
        ("source_id", "name"),
        ("organization", "version"),
        ("is_active", "is_current"),
        "hut",
        "review_status",
        "review_comment",
        "location",
        "source_data",
        "source_properties",
        "previous_object",
        ("created", "modified"),
    )
    list_max_show_all = 2000
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    @display(
        description=_("Status"),  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
        ordering="status",
        label={
            HutSource.ReviewStatusChoices.new: "warning",  # green
            HutSource.ReviewStatusChoices.review: "info",  # blue
            HutSource.ReviewStatusChoices.done: "success",  # red
            HutSource.ReviewStatusChoices.failed: "danger",  # red
        },
    )
    def review_tag(self, obj):
        return obj.review_status

    @display(description=_("Review Comment"))  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def review_comment_short(self, obj):  # new
        return text_shorten_html(obj.review_comment, width=100)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields["previous_object"].queryset = (  # pyright: ignore[reportAttributeAccessIssue] — ModelChoiceField attr
                # HutSource.objects.select_related("organization")
                HutSource.objects.filter(
                    source_id=obj.source_id, version__lt=obj.version
                ).order_by("-version")
            )
        return form

    # actions_list = ["changelist_global_action_import"]
    actions_row = (
        "action_row_set_review_to_done",
        "action_row_set_review_to_review",
        "action_row_set_inactive",
        "action_row_delete",
    )
    # actions_detail = ["change_detail_action_block"]
    # actions_submit_line = ["submit_line_action_activate"]

    @action(description=_(mark_safe("set to <b>done</b>")), permissions=["change"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_set_review_to_done(
        self, request: HttpRequest, object_id: int
    ):  # obj: HutSource):
        obj = HutSource.objects.get(id=object_id)
        obj.review_status = HutSource.ReviewStatusChoices.done
        obj.save()
        return redirect(request.META.get("HTTP_REFERER") or "/")  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(description=_(mark_safe("set to <b>review</b>")), permissions=["change"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_set_review_to_review(
        self, request: HttpRequest, object_id: int
    ):  # obj: HutSource):
        obj = HutSource.objects.get(id=object_id)
        obj.review_status = HutSource.ReviewStatusChoices.review
        obj.save()
        return redirect(request.META.get("HTTP_REFERER") or "/")  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(
        description=_(mark_safe("set to <b>reject</b> (inactive)")),  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
        permissions=["delete"],
    )
    def action_row_set_inactive(
        self, request: HttpRequest, object_id: int
    ):  # obj: HutSource):
        obj = HutSource.objects.get(id=object_id)
        obj.review_status = HutSource.ReviewStatusChoices.reject
        obj.is_active = False
        obj.save()
        return redirect(request.META.get("HTTP_REFERER") or "/")  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)

    @action(description=_(mark_safe("<b>delete</b> entry")), permissions=["delete"])  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
    def action_row_delete(
        self, request: HttpRequest, object_id: int
    ):  # obj: HutSource):
        obj = HutSource.objects.get(id=object_id)
        obj.delete()
        return redirect(request.META.get("HTTP_REFERER") or "/")  # pyright: ignore[reportArgumentType]  # lazy-gettext idiom (i18n-safe)
