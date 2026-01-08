from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ExternalGeonamesConfig(AppConfig):
    name = "server.apps.external_geonames"
    label = "external_geonames"
    verbose_name = _("External GeoNames")
