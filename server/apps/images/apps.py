from typing import Any

from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class HutsConfig(AppConfig):
    name = "server.apps.images"
    verbose_name = _("Images")
