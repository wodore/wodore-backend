from typing import Any

from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


def _create_organizations(sender: "HutsConfig", **kwargs: Any) -> None:
    from server.apps.organizations.models import Organization

    if not Organization.objects.exists():
        call_command("organizations", add=True, force=True)


class HutsConfig(AppConfig):
    name = "server.apps.organizations"
    verbose_name = _("Organizations")

    def ready(self) -> None:
        post_migrate.connect(_create_organizations, sender=self)
