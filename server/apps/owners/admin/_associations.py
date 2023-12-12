from typing import ClassVar

from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

# TODO: move manager
# from server.apps.manager.admin import ModelAdmin

# from ..models import (
#    Hut,
#    HutContactAssociation,
#    HutOrganizationAssociation,
#    Owner,
#    OwnerContactAssociation,
# )
#
#
### ADMIN
# @admin.register(HutContactAssociation)
# class HutContactAssociationsAdmin(ModelAdmin):
#    list_display = ("hut", "contact", "order")
#
