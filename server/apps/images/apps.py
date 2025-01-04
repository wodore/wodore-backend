from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HutsConfig(AppConfig):
    name = "server.apps.images"
    verbose_name = _("Images")
