from django.contrib import admin

# Register your models here.

from django.conf import settings
from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.contrib.auth.models import Group, User
from django.contrib.auth.admin import GroupAdmin, UserAdmin

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.widgets import UnfoldAdminColorInputWidget, UnfoldAdminTextInputWidget
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from colorfield.fields import ColorWidget, ColorField


from django_jsonform.forms.fields import JSONFormField
from django_jsonform.widgets import JSONFormWidget

from django.db import models

from .widgets import UnfoldJSONSuit, UnfoldReadonlyJSONSuit

from jsonsuit.widgets import JSONSuit, ReadonlyJSONSuit


class ModelAdmin(GISModelAdmin, UnfoldModelAdmin):
    # Display submit button in filters
    list_filter_submit = False
    formfield_overrides = {models.JSONField: {"widget": UnfoldJSONSuit}}
    # gis_widget_kwargs = {"default_zoom": 7}

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
        new_class = type(f"{original_class.__name__}Unfold", (ModelAdmin, original_class), {})
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
