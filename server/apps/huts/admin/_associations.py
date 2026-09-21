from typing import ClassVar

from django import forms
from django.contrib import admin
from django.db import models
from django.forms import ModelForm
from django.utils.translation import gettext_lazy as _

from unfold import admin as unfold_admin

# TODO: move manager
from server.apps.manager.admin import ModelAdmin
from server.apps.manager.widgets import UnfoldJSONSuit, UnfoldReadonlyJSONSuit
from server.apps.owners.models import Owner

from ..models import (
    Hut,
    HutContactAssociation,
    HutImageAssociation,
    HutOrganizationAssociation,
)


## Custom Admin Forms (private)
class _HutOrganizationAssociationForm(ModelForm):
    schema = forms.JSONField(
        label=_("Property JSON Schema"), required=False, widget=UnfoldReadonlyJSONSuit()
    )

    class Meta:
        model = HutOrganizationAssociation
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        initial = kwargs.get("initial", {})

        if instance:
            initial = {"schema": instance.organization.props_schema}

        super().__init__(*args, **kwargs, initial=initial)

    def save(self, commit=True):
        return super().save(commit)


## INLINES


class HutContactAssociationEditInline(unfold_admin.TabularInline):
    """Hut showing contacts"""

    model = Hut.contact_set.through
    tab = True
    fields = ("contact", "order")
    autocomplete_fields = ("contact",)
    extra = 0
    verbose_name = _("Contact")


class HutImageAssociationEditInline(unfold_admin.TabularInline):
    """Hut showing images"""

    model = Hut.image_set.through
    # tab = False
    fields = ("image", "order")
    autocomplete_fields = ("image",)
    extra = 0
    verbose_name = _("Image")
    # template = "huts/image_inline.html"


class ContactHutAssociationEditInline(unfold_admin.TabularInline):
    """Contact showing huts"""

    model = Hut.contact_set.through
    tab = True
    fields = ("hut",)  # hot to acces "hut__name"
    autocomplete_fields = ("hut",)
    extra = 0
    verbose_name = _("Hut")


class OwnerContactAssociationEditInline(HutContactAssociationEditInline):
    """Owner showing contacts"""

    model = Owner.contacts.through
    tab = True
    # fields = ("contact", "order")


class ContactOwnerAssociationEditInline(unfold_admin.TabularInline):
    """Contact showing owner"""

    model = Owner.contacts.through
    tab = True
    fields = ("hut_owner",)
    autocomplete_fields = ("hut_owner",)
    extra = 0
    verbose_name = _("Owner")
    # fk_name = "contact"


class HutOrganizationAssociationEditInline(unfold_admin.StackedInline):
    """Hut <> Organization"""

    form = _HutOrganizationAssociationForm
    tab = True
    model = Hut.org_set.through
    fields = (("organization", "source_id"), "props", "schema")
    autocomplete_fields = ("organization",)  # ~680 orgs (OSM brands): no plain select
    extra = 0
    # classes = ("collapse",)  # Commented out to keep tab expanded by default
    formfield_overrides: ClassVar = {models.JSONField: {"widget": UnfoldJSONSuit}}
    verbose_name = _("Edit Source")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization")


class HutOrganizationAssociationViewInline(unfold_admin.TabularInline):
    model = Hut.org_set.through
    tab = True
    fields = ("organization", "source_id")
    # readonly_fields = ["organization", "source_id"]
    autocomplete_fields = ("organization",)  # ~680 orgs (OSM brands): no plain select
    can_delete = False
    extra = 0
    show_change_link = True
    verbose_name = _("Source")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization")

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj=None):
        return False


## ADMIN
@admin.register(HutContactAssociation)
class HutContactAssociationsAdmin(ModelAdmin):
    list_display = ("hut", "contact", "order")


@admin.register(HutImageAssociation)
class HutImageAssociationAdmin(ModelAdmin):
    list_display = ("hut", "image", "order")
    autocomplete_fields = ("hut", "image")


@admin.register(HutOrganizationAssociation)
class HutOrganizationAssociationAdmin(ModelAdmin):
    list_display = ("hut", "organization", "source_id")
    list_filter = ("organization",)
    search_fields = ("hut__name", "hut__slug", "source_id")
    autocomplete_fields = ("hut", "organization")
