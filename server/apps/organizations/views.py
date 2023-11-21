from django.shortcuts import render

# Create your views here.
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.views.generic.detail import DetailView
from .models import Organization
from django.contrib import admin

from ..djjmt.utils import override, django_get_normalised_language, activate


class OrganizationDetailView(PermissionRequiredMixin, DetailView):
    #
    permission_required = "organiations.view_organization"
    template_name = "organizations/detail.html"
    model = Organization

    def get_context_data(self, **kwargs):
        activate(django_get_normalised_language())
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            "opts": self.model._meta,
            "org": self.object,
        }
