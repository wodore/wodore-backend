from typing import ClassVar

from django.contrib import admin
from django.db import models
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin
from unfold.decorators import display

from server.apps.manager.admin import ModelAdmin
from server.apps.manager.widgets import UnfoldReadonlyJSONSuit

from ..models import (
    HutSource,
    ReviewStatusChoices,
)


## INLINES
class HutSourceViewInline(unfold_admin.StackedInline):
    model = HutSource
    readonly_fields = (
        "created",
        "modified",
        "organization",
        "source_id",
        "name",
    )  # , "source_data"] # TODO formated json
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    fields = (("organization", "source_id"), ("review_status"), ("review_comment"), "source_data", "is_active")
    extra = 0
    max_num = 20
    show_change_link = True
    can_delete = False
    classes = ("collapse",)
    formfield_overrides: ClassVar = {models.JSONField: {"widget": UnfoldReadonlyJSONSuit}}

    def has_add_permission(self, request, obj):
        return False


## ADMIN
@admin.register(HutSource)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class HutsSourceAdmin(ModelAdmin[HutSource]):
    """Admin panel example for ``BlogPost`` model."""

    # view_on_site = True
    # list_select_related = True
    list_display = ("name", "organization", "review_comment", "is_active", "is_current", "version", "review_tag")
    list_filter = ("organization", "review_status", "is_active", "is_current", "version")
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
        "point",
        "source_data",
        "previous_object",
        ("created", "modified"),
    )
    list_max_show_all = 2000
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}

    @display(
        description=_("Status"),
        ordering="status",
        label={
            ReviewStatusChoices.new: "warning",  # green
            ReviewStatusChoices.review: "info",  # blue
            ReviewStatusChoices.done: "success",  # red
            # ReviewStatusChoices.done: "warning",  # orange
            # ReviewStatusChoices.reject: "danger",  # red
        },
    )
    def review_tag(self, obj):
        return obj.review_status

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields["previous_object"].queryset = (
                # HutSource.objects.select_related("organization")
                HutSource.objects.filter(source_id=obj.source_id, version__lt=obj.version).order_by("-version")
            )
        return form
