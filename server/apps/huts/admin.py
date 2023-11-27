from django.contrib import admin
from manager.admin import ModelAdmin
from .models import HutSource

# Register your models here.


@admin.register(HutSource)
# class OrganizationAdmin(ActiveLanguageMixin, admin.ModelAdmin[Organization]):
class OrganizationAdmin(ModelAdmin[HutSource]):
    """Admin panel example for ``BlogPost`` model."""

    view_on_site = True
    list_select_related = True
