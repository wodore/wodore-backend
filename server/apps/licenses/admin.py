from django.contrib import admin

# Models
from django.utils.safestring import mark_safe

from unfold.decorators import display

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
    list_display = (
        "slug",
        "name_i18n",
        "is_active",
        "attribution_required",
        "no_commercial",
        "no_modifying",
        "share_alike",
        "no_publication",
        "order_small",
    )
    list_display_links = ("slug", "name_i18n")
    search_fields = ("slug", "name_i18n", "fullname_i18n")
    readonly_fields = (
        "name_i18n",
        "fullname_i18n",
        "description_i18n",
        "link_i18n",
        "created",
        "modified",
    )

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
