from typing import Any

from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


def _create_licenses(sender: "HutsConfig", **kwargs: Any) -> None:
    from server.apps.licenses.models import License

    if not License.objects.exists():
        call_command("licenses")


class HutsConfig(AppConfig):
    name = "server.apps.licenses"
    verbose_name = _("Licenses")

    def ready(self) -> None:
        post_migrate.connect(_create_licenses, sender=self)
