from django.contrib import admin
from manager.admin import ModelAdmin
from .models import HutSource
from unfold.decorators import display
from django.utils.translation import gettext_lazy as _
from django.db.models import F
from huts.models import HutSource, ReviewStatusChoices

# Register your models here.


@admin.register(HutSource)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class HutsAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    # view_on_site = True
    list_select_related = True
    list_display = ["name", "organization", "review_comment", "is_active", "is_current", "version", "review_tag"]
    list_filter = ["organization", "review_status", "is_active", "is_current", "version"]
    list_display_links = ["name"]
    search_fields = ["name"]
    sortable_by = ["name", "organization"]
    readonly_fields = ["created", "modified"]

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
        form = super(HutsAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields["previous_object"].queryset = (
                # HutSource.objects.select_related("organization")
                HutSource.objects.filter(source_id=obj.source_id, version__lt=obj.version).order_by("-version")
            )
        return form
