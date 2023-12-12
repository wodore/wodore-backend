from manager.admin import ModelAdmin
from manager.widgets import UnfoldJSONSuit, UnfoldReadonlyJSONSuit
from unfold import admin as unfold_admin
from unfold.decorators import display

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.forms import ModelForm
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from translations.forms import required_i18n_fields_form_factory

from .forms import HutAdminFieldsets
from .models import (
    Contact,
    ContactFunction,
    Hut,
    HutContactAssociation,
    HutOrganizationAssociation,
    HutSource,
    HutType,
    Owner,
    ReviewStatusChoices,
)

# Register your models here.


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
        "review_comment",
        "review_status",
        "point",
        "source_data",
        "previous_object",
        ("created", "modified"),
    )
    list_max_show_all = 2000
    radio_fields = {"review_status": admin.HORIZONTAL}

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


class HutSourceInline(unfold_admin.StackedInline):
    model = HutSource
    readonly_fields = (
        "created",
        "modified",
        "organization",
        "source_id",
        "name",
    )  # , "source_data"] # TODO formated json
    radio_fields = {"review_status": admin.HORIZONTAL}
    fields = (("organization", "source_id"), ("review_status"), ("review_comment"), "source_data", "is_active")
    extra = 0
    max_num = 20
    show_change_link = True
    can_delete = False
    classes = ("collapse",)
    formfield_overrides = {models.JSONField: {"widget": UnfoldReadonlyJSONSuit}}

    def has_add_permission(self, request, obj):
        return False


class HutOrganizationAssociationViewInline(unfold_admin.TabularInline):
    model = Hut.organizations.through
    fields = ("organization", "source_id")
    # readonly_fields = ["organization", "source_id"]
    can_delete = False
    extra = 0
    verbose_name = _("Organization")

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj):
        return False


class HutContactAssociationViewInline(unfold_admin.TabularInline):
    model = Hut.contacts.through
    fields = ("contact", "order")
    autocomplete_fields = ("contact",)
    # readonly_fields = ["organization", "source_id"]
    # can_delete = False
    extra = 0
    verbose_name = _("Contact")

    # def has_add_permission(self, request, obj):
    #    return False

    # def has_change_permission(self, request, obj):
    #    return False


class OrgAdminForm(ModelForm):
    schema = forms.JSONField(label="Props Schema", required=False, widget=UnfoldReadonlyJSONSuit())

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
        # self.instance.customer_full_name = self.cleaned_data["first_name"] + " " + self.cleaned_data["last_name"]
        return super().save(commit)


class HutOrganizationAssociationEditInline(unfold_admin.StackedInline):
    form = OrgAdminForm
    model = Hut.organizations.through
    fields = (("organization", "source_id"), "props", "schema")
    extra = 0
    classes = ("collapse",)
    formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}
    verbose_name = _("Edit Organization")


@admin.register(Hut)
class HutsAdmin(ModelAdmin):
    search_fields = ("name",)
    list_select_related = (
        "type",
        "owner",
    )
    form = required_i18n_fields_form_factory("name")
    radio_fields = {"review_status": admin.HORIZONTAL}
    # list_select_related = ("organizations", "organizations__details")
    # list_select_related = ["organizations__source"]
    list_display = ("symbol_img", "title", "location", "elevation", "type", "logo_orgs", "is_active", "review_tag")
    list_display_links = ("symbol_img", "title")
    fieldsets = HutAdminFieldsets
    readonly_fields = (
        "name_i18n",
        "description_i18n",
        "note_i18n",
        "created",
        "modified",
    )
    list_per_page = 100

    inlines = (
        HutContactAssociationViewInline,
        HutOrganizationAssociationViewInline,
        HutOrganizationAssociationEditInline,
        HutSourceInline,
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


@admin.register(Contact)
class ContactsAdmin(ModelAdmin):
    search_fields = ("name", "email", "function__name_i18n")
    list_display = ("name", "email", "mobile", "phone", "function", "is_active", "is_public")
    list_filter = ("function", "is_active", "is_public")
    readonly_fields = ("note_i18n",)
    fieldsets = (
        (
            _("Main Information"),
            {
                "fields": (
                    ("is_active", "is_public"),
                    ("name", "email"),
                    "function",
                    ("mobile", "phone"),
                    "url",
                    "address",
                    "note_i18n",
                )
            },
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [f"note_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
    )


@admin.register(Owner)
class OwnersAdmin(ModelAdmin):
    search_fields = ("name",)
    list_display = ("name", "url", "note")


@admin.register(ContactFunction)
class ContactFunctionsAdmin(ModelAdmin):
    search_fields = ("name",)
    list_display = ("slug", "name", "priority")

    # @display(description="level", ordering="priority")
    # def prio(self, obj):  # new
    #    return mark_safe(f"<small>{obj.priority}</small>")


def required_i18n_fields_form(*fields):
    class TransForm(ModelForm):
        def clean(self):
            for field in fields:
                translations = [self.cleaned_data.get(f"{field}_{code}", None) for code in settings.LANGUAGE_CODES]
                if not any(translations):
                    raise ValidationError(
                        mark_safe(_(f"At least one <i>{field}</i> field under <b>Translations</b> is required."))
                    )

            return self.cleaned_data

    return TransForm


# ActiveLanguageMixin
@admin.register(HutType)
class HutTypesAdmin(ModelAdmin):
    form = required_i18n_fields_form("name")
    search_fields = ("name",)
    list_display = ("title", "symbol_img", "icon_img", "comfort", "slug")
    readonly_fields = ("name_i18n", "description_i18n")
    fieldsets = (
        (
            _("Main Information"),
            {"fields": (("slug", "name_i18n", "level"), "description_i18n")},
        ),
        (
            _("Translations"),
            {
                "classes": ["collapse"],
                "fields": [
                    tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
                ]
                + [f"description_{code}" for code in settings.LANGUAGE_CODES],
            },
        ),
        (
            _("Symbols & Icon"),
            {"fields": (("symbol", "symbol_simple", "icon"),)},
        ),
    )

    @display(header=True, description=_("Name and Description"), ordering=Lower("name_i18n"))
    def title(self, obj):
        return (obj.name_i18n, obj.description_i18n, self.avatar(obj.symbol_simple.url))

    @display(description="symbol")
    def symbol_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.symbol.url}" width = "34"/>')

    @display(description="simple")
    def icon_img(self, obj):  # new
        return mark_safe(f'<img src = "{obj.icon.url}" width = "16"/>')

    def avatar(self, url):  # new
        return mark_safe(f'<img src = "{url}" width = "20"/>')

    @display(description="level", ordering="level")
    def comfort(self, obj):  # new
        return mark_safe(f"<small>{obj.level}</small>")


@admin.register(HutContactAssociation)
class HutContactAssociationsAdmin(ModelAdmin):
    list_display = ("hut", "contact", "order")
