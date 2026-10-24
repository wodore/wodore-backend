from collections.abc import Iterator
from typing import Any, TypeVar, cast, override

from colorfield.fields import ColorWidget
from jsonsuit.widgets import JSONSuit, ReadonlyJSONSuit

# Register your models here.
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.contrib.auth.admin import (  # shadowed below (Django admin idiom)
    GroupAdmin,
    UserAdmin,
)
from django.contrib.auth.models import Group
from django.contrib.gis.admin import GISModelAdmin
from django.db import models
from django.forms import ModelForm
from django.http import HttpRequest

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.contrib.filters.admin import RelatedCheckboxFilter
from unfold.contrib.filters.admin.mixins import MultiValueMixin
from unfold.contrib.filters.forms import CheckboxForm
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminColorInputWidget

from server.apps.accounts.models import User as AccountsUser

from .widgets import UnfoldJSONSuit, UnfoldReadonlyJSONSuit

# Generic over the admin's model: subscripted usages (``UserAdmin[AccountsUser]``
# below) pin it precisely. The ``Any`` default preserves the pre-ratchet
# behavior of bare subclassers in other apps (model parameter unsolved).
_ModelT = TypeVar("_ModelT", bound=models.Model, default=Any)


class ModelAdmin(GISModelAdmin[_ModelT], UnfoldModelAdmin):
    # Display submit button in filters
    list_filter_submit = False
    formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}
    # gis_widget_kwargs = {"width": 600, "height": 400}

    @override
    def get_form(
        self,
        request: HttpRequest,
        obj: _ModelT | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[ModelForm[_ModelT]]:
        form = super().get_form(request, obj, change, **kwargs)
        for key, field in form.base_fields.items():
            if isinstance(field.widget, ColorWidget):
                form.base_fields[key].widget = UnfoldAdminColorInputWidget()
            if isinstance(field.widget, JSONSuit):
                form.base_fields[key].widget = UnfoldJSONSuit()
            if isinstance(field.widget, ReadonlyJSONSuit):
                form.base_fields[key].widget = UnfoldReadonlyJSONSuit()
            # if isinstance(model, JSONFormField):
            #    schema = {
            #        "keys": {
            #            "de": {"title": "German", "type": "string", "widget": "text"},
            #            "en": {"title": "English", "type": "string", "widget": "text"},
            #            "fr": {"title": "French", "type": "string", "widget": "text"},
            #            "it": {"title": "Italian", "type": "string", "widget": "text"},
            #        },
            #        "type": "dict",
            #    }
            #    field_class = ""
            #    form.base_fields[key].widget = JSONFormWidget(schema=schema, attrs={"class": field_class})

        return form

    # formfield_overrides = {
    #    JSONField: {
    #        "widget": JSONFormWidget(schema=ITEMS_SCHEMA),
    #    }
    # }
    # why does this not work?
    # formfield_overrides = {
    # }


models_to_reregister = []
try:
    from axes.admin import AccessAttempt, AccessFailureLog, AccessLog

    axes = [AccessAttempt, AccessFailureLog, AccessLog]
    models_to_reregister += axes
except RuntimeError:
    ...
users = [AccountsUser, Group]
models_to_reregister += users
registry = admin.site._registry
new_registry_items = {}
registry_dict = registry.copy()
for model, admin_model_object in registry_dict.items():
    if model in models_to_reregister:
        original_class = admin_model_object.__class__
        new_class = type(
            f"{original_class.__name__}Unfold", (ModelAdmin, original_class), {}
        )
        new_registry_items[model] = new_class

for model, admin_model in new_registry_items.items():
    admin.site.unregister(model)
    admin.site.register(model, admin_model)

# Group and User (custom email-identity user model)


@admin.register(AccountsUser)
class UserAdmin(UserAdmin[AccountsUser], ModelAdmin[AccountsUser]):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = ("email", "is_staff", "is_superuser", "is_active")
    ordering = ("email",)
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal info",
            {"fields": ("first_name", "last_name")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(GroupAdmin, ModelAdmin[Group]):
    pass


# ---------------------------------------------------------------------------
# Django-Q2 admin — Unfold-styled with command dropdown in Schedule
# ---------------------------------------------------------------------------

from django_q.admin import FailAdmin as QFailAdmin
from django_q.admin import QueueAdmin as QQueueAdmin
from django_q.admin import ScheduleAdmin as QScheduleAdmin
from django_q.admin import TaskAdmin as QTaskAdmin
from django_q.models import Failure, OrmQ, Schedule, Success

from unfold.widgets import (
    UnfoldAdminSelectWidget,
    UnfoldAdminTextInputWidget,
)

for _model in [Schedule, Success, Failure, OrmQ]:
    try:
        admin.site.unregister(_model)
    except admin.sites.NotRegistered:  # type: ignore  # dynamic attr: plugin-less inference gap
        pass


@admin.register(Schedule)
class CustomScheduleAdmin(QScheduleAdmin, ModelAdmin[Schedule]):
    """Schedule admin with a func dropdown listing registered commands."""

    fieldsets = (
        (
            None,
            {
                "fields": ("name", "func", "hook", "args", "kwargs"),
            },
        ),
        (
            "Schedule",
            {
                "fields": (
                    "schedule_type",
                    "minutes",
                    "cron",
                    "repeats",
                    "next_run",
                    "intended_date_kwarg",
                ),
            },
        ),
        (
            "Advanced",
            {
                "classes": ("collapse",),
                "fields": ("cluster",),
            },
        ),
    )

    conditional_fields = {
        "minutes": "schedule_type == 'I'",
        "cron": "schedule_type == 'C'",
    }

    @override
    def get_form(
        self,
        request: HttpRequest,
        obj: Schedule | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[ModelForm[Schedule]]:
        from django_admin_runner.registry import _registry

        form_class = super().get_form(request, obj, change=change, **kwargs)

        # Build choices from the registry — blank option allows free-text entry
        choices = [("", "---------")]
        for cmd_name, entry in sorted(_registry.items()):
            choices.append(
                ("django_admin_runner.tasks.execute_command", entry["display_name"])
            )

        form_class.base_fields["func"].widget = UnfoldAdminSelectWidget(choices=choices)
        form_class.base_fields["args"].widget = UnfoldAdminTextInputWidget()
        form_class.base_fields["kwargs"].widget = UnfoldAdminTextInputWidget()

        form_class.base_fields["minutes"].label = "Interval (minutes)"
        form_class.base_fields[
            "minutes"
        ].help_text = "Only used when Schedule Type is set to Minutes"
        return form_class


@admin.register(Success)
class UnfoldSuccessAdmin(QTaskAdmin, ModelAdmin[Success]):
    pass


@admin.register(Failure)
class UnfoldFailureAdmin(QFailAdmin, ModelAdmin[Failure]):
    pass


@admin.register(OrmQ)
class UnfoldQueueAdmin(QQueueAdmin, ModelAdmin[OrmQ]):
    pass


class RelatedOnlyCheckboxFilter(MultiValueMixin, admin.RelatedOnlyFieldListFilter):
    """Checkboxes over only the related values actually in use.

    Combines Django's `RelatedOnlyFieldListFilter` (limits choices to the
    related objects that occur in the data) with unfold's checkbox form
    rendering and multi-select semantics (`RelatedCheckboxFilter` shows ALL
    related objects — with ~680 organizations in this project that is not
    usable).
    """

    template = "unfold/filters/filters_field.html"
    form_class = CheckboxForm

    @override
    def choices(self, changelist: ChangeList) -> Iterator[Any]:
        """Render checkbox forms for the related values actually in use.

        Delegates to unfold's ``RelatedCheckboxFilter.choices`` rendering:
        ``self`` duck-types as that filter (``cast``), because
        ``lookup_choices`` and the facet machinery come from the
        ``RelatedOnlyFieldListFilter`` base, not from unfold's class.
        Yields unfold's ``{"form": ...}`` dicts, not the choice dicts of the
        stock admin filter (the stub's shape is private and does not fit).
        """
        yield from RelatedCheckboxFilter.choices(
            cast(RelatedCheckboxFilter, self), changelist
        )
