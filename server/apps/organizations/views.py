import json

from django.contrib import admin

# Create your views here.
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.urls import reverse
from django.views.generic.detail import DetailView

from server.apps.djjmt.utils import activate, django_get_normalised_language

from .models import Organization


class OrganizationDetailView(PermissionRequiredMixin, DetailView):
    #
    permission_required = "organiations.view_organization"
    template_name = "organizations/detail.html"
    model = Organization

    def get_context_data(self, **kwargs):
        activate(django_get_normalised_language())
        context = {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            "opts": self.model._meta,
            "org": self.object,
            "config_json": json.dumps(self.object.config, indent=2),
            "props_schema_json": json.dumps(self.object.props_schema, indent=2),
            "original": self.object.name,
            "title": f"View Organization {self.object.name}",
            "edit_url": reverse("admin:organizations_organization_change", args=[self.object.pk]),
        }
        return context
