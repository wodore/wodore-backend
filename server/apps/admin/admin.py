from django.contrib import admin

# Register your models here.

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.contrib.auth.admin import GroupAdmin, UserAdmin

from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.widgets import UnfoldAdminColorInputWidget
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from colorfield.fields import ColorWidget, ColorField


class ModelAdmin(UnfoldModelAdmin):
    # Display submit button in filters
    list_filter_submit = True

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        for key, model in form.base_fields.items():
            if isinstance(model.widget, ColorWidget):
                form.base_fields[key].widget = UnfoldAdminColorInputWidget()
        return form

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
