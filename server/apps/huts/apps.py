from typing import Any

from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


def _create_hut_types(sender: "HutsConfig", **kwargs: Any) -> None:
    from server.apps.huts.models import HutType

    if not HutType.objects.exists():
        call_command("hut_types", add=True, force=True)


class HutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.huts"
    verbose_name = _("Huts")

    def ready(self) -> None:
        post_migrate.connect(_create_hut_types, sender=self)
