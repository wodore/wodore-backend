from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GeomentriesConfig(AppConfig):
    name = "server.apps.geometries"
    # label = "external_geonames"
    verbose_name = _("Geometries")
