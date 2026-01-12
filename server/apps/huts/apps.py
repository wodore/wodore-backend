from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


def _create_hut_types(sender: "HutsConfig", **kwargs: Any) -> None:
    # HutType is now a wrapper around Category - no need to auto-create
    # Categories are created via migrations and can be managed via admin
    pass


class HutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.huts"
    verbose_name = _("Huts")

    def ready(self) -> None:
        post_migrate.connect(_create_hut_types, sender=self)
