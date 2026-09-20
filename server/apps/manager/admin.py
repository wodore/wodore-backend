from colorfield.fields import ColorWidget
from jsonsuit.widgets import JSONSuit, ReadonlyJSONSuit

# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User
from django.contrib.gis.admin import GISModelAdmin
from django.db import models

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminColorInputWidget

from .widgets import UnfoldJSONSuit, UnfoldReadonlyJSONSuit


class ModelAdmin(GISModelAdmin, UnfoldModelAdmin):
    # Display submit button in filters
    list_filter_submit = False
    formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}
    # gis_widget_kwargs = {"width": 600, "height": 400}

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        for key, model in form.base_fields.items():
            if isinstance(model.widget, ColorWidget):
                form.base_fields[key].widget = UnfoldAdminColorInputWidget()
            if isinstance(model.widget, JSONSuit):
                form.base_fields[key].widget = UnfoldJSONSuit()
            if isinstance(model.widget, ReadonlyJSONSuit):
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
users = [User, Group]
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

# Group and User

admin.site.unregister(User)


@admin.register(User)
class UserAdmin(UserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    # list_filter_submit =


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(GroupAdmin, ModelAdmin):
    pass


# ---------------------------------------------------------------------------
# Django-Q2 admin — Unfold-styled with command dropdown in Schedule
# ---------------------------------------------------------------------------

from django_q.admin import FailAdmin as QFailAdmin  # noqa: E402
from django_q.admin import QueueAdmin as QQueueAdmin  # noqa: E402
from django_q.admin import ScheduleAdmin as QScheduleAdmin  # noqa: E402
from django_q.admin import TaskAdmin as QTaskAdmin  # noqa: E402
from django_q.models import Failure, OrmQ, Schedule, Success  # noqa: E402
from unfold.widgets import (  # noqa: E402
    UnfoldAdminSelectWidget,
    UnfoldAdminTextInputWidget,
)

for _model in [Schedule, Success, Failure, OrmQ]:
    try:
        admin.site.unregister(_model)
    except admin.sites.NotRegistered:
        pass


@admin.register(Schedule)
class CustomScheduleAdmin(QScheduleAdmin, ModelAdmin):
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

    def get_form(self, request, obj=None, **kwargs):
        from django_admin_runner.registry import _registry

        form_class = super().get_form(request, obj, **kwargs)

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
class UnfoldSuccessAdmin(QTaskAdmin, ModelAdmin):
    pass


@admin.register(Failure)
class UnfoldFailureAdmin(QFailAdmin, ModelAdmin):
    pass


@admin.register(OrmQ)
class UnfoldQueueAdmin(QQueueAdmin, ModelAdmin):
    pass
