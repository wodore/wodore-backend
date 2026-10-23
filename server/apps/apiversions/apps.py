from django.apps import AppConfig


class ApiversionsConfig(AppConfig):
    name = "server.apps.apiversions"
    verbose_name = "API Versioning"

    def ready(self) -> None:
        # Register the registry-integrity system check (checks run on every
        # management command; importing checks registers the hook).
        from . import checks  # noqa: F401
