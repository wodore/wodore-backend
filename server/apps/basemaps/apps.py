"""App configuration for basemaps."""

from typing import override

from django.apps import AppConfig


class BasemapsConfig(AppConfig):
    """Basemaps: map layer catalog and style serving."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.basemaps"
    verbose_name = "Basemaps & Overlays"

    @override
    def ready(self) -> None:
        """Env-registry edits flip layer availability at runtime.

        Reset the availability warning memo and drop the catalog
        version cache whenever an ``envvars.EnvVar`` row changes (the
        row snapshot itself is invalidated by ``envvars.registry``).
        String senders keep the import graph lazy.
        """
        from django.db.models.signals import post_delete, post_save

        from .api import _registry_changed

        post_save.connect(
            _registry_changed,
            sender="envvars.envvar",
            dispatch_uid="basemaps.envvar-changed",
        )
        post_delete.connect(
            _registry_changed,
            sender="envvars.envvar",
            dispatch_uid="basemaps.envvar-changed",
        )
