from typing import ClassVar
from django.contrib import admin

# Models
from django.utils.safestring import mark_safe

from server.apps.geometries.schemas import ReviewStatus
from unfold.contrib.filters.admin import (
    AutocompleteSelectMultipleFilter,
    ChoicesCheckboxFilter,
)
from unfold.decorators import display
from django.utils.translation import gettext_lazy as _

from server.apps.manager.admin import ModelAdmin
from server.apps.translations.forms import required_i18n_fields_form_factory

# try:
#    from unfold.admin import ModelAdmin
# except ModuleNotFoundError:
#    from django.contrib.admin import ModelAdmin
from .forms import LicenseAdminFieldsets

# Register your models here.
from .models import License


@admin.register(License)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class LicenseAdmin(ModelAdmin):
    """Admin panel example for ``BlogPost`` model."""

    form = required_i18n_fields_form_factory("name", "fullname")
    fieldsets = LicenseAdminFieldsets
    view_on_site = True
    list_filter_submit = True  # Add submit button for filters
    autocomplete_fields = ("category",)
    radio_fields: ClassVar = {"review_status": admin.HORIZONTAL}
    list_display = (
        "slug",
        "name_i18n",
        "category",
        "is_active",
        "attribution_required",
        "no_commercial",
        "no_modifying",
        "share_alike",
        "no_publication",
        "review_tag",
        "order_small",
    )
    list_display_links = ("slug", "name_i18n")
    list_filter = (
        (
            "review_status",
            ChoicesCheckboxFilter,
        ),  # Filter by review status with checkboxes
        "is_active",
        ("category", AutocompleteSelectMultipleFilter),
    )
    search_fields = ("slug", "name_i18n", "fullname_i18n", "review_comment")
    readonly_fields = (
        "name_i18n",
        "fullname_i18n",
        "description_i18n",
        "url_i18n",
        "created",
        "modified",
    )

    @display(
        description=_("Review"),
        label={
            ReviewStatus.NEW: "warning",
            ReviewStatus.REVIEW: "info",
            ReviewStatus.WORK: "danger",
            ReviewStatus.DONE: "success",
        },
    )
    def review_tag(self, obj: License) -> str:
        """Display review status as colored label."""
        return obj.review_status

    # formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}

    # def get_urls(self):
    #    return [
    #        path(
    #            "<pk>/detail",
    #            self.admin_site.admin_view(OrganizationDetailView.as_view()),
    #            name="organizations_organization_detail",
    #        ),
    #        *super().get_urls(),
    #    ]

    # @display(description="")
    # def detail(self, obj: Organization) -> str:
    #    url = reverse("admin:organizations_organization_detail", args=[obj.pk])
    #    view = (
    #        f'<span><a class="text-sm" href="{url}"> <span class="material-symbols-outlined"> visibility </span> </a>'
    #    )
    #    url = reverse("admin:organizations_organization_change", args=[obj.pk])
    #    edit = f'<a class="text-sm" href="{url}"> <span class="material-symbols-outlined"> edit </span> </a><span>'
    #    return format_html(view + edit)

    # @display(header=True)
    # def organization(self, obj):
    #    """
    #    Third argument is short text which will appear as prefix in circle
    #    """
    #    return (obj.name_i18n, obj.fullname_i18n, self.logo_thumb(obj))

    @display(description="#", ordering=None)
    def order_small(self, obj):
        return mark_safe(f"<small>{obj.order}</small>")
