"""App configuration for basemaps."""

from django.apps import AppConfig


class BasemapsConfig(AppConfig):
    """Basemaps: map layer catalog and style serving."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.basemaps"
    verbose_name = "Basemaps & Overlays"
