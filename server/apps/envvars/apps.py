"""App configuration for envvars."""

from django.apps import AppConfig


class EnvVarsConfig(AppConfig):
    """EnvVars: admin-managed environment variable registry."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.envvars"
    verbose_name = "Environment Variables"

    def ready(self) -> None:
        """Wire registry-snapshot invalidation."""
        from . import registry

        registry.connect()
