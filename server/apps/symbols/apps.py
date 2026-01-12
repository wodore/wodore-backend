from django.apps import AppConfig


class SymbolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.apps.symbols"
    verbose_name = "Symbols"

    # TODO: Add any app-specific configuration if needed
    # e.g., signals, ready() method for initialization
