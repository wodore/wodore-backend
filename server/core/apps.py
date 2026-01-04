"""
Core app configuration.
"""

import pgtrigger
from django.apps import AppConfig, apps


# Module-level flag to prevent duplicate trigger registration
_triggers_registered = False


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "server.core"
    verbose_name = "Core"

    def ready(self):
        """
        Register PostgreSQL triggers for all TimeStampedModel subclasses.

        This automatically applies the update_modified trigger to all models
        that inherit from TimeStampedModel, without requiring each model to
        explicitly inherit the Meta class.
        """
        global _triggers_registered

        # Guard against multiple calls to ready()
        if _triggers_registered:
            return
        _triggers_registered = True

        from server.core.models import TimeStampedModel

        # Get all concrete models that inherit from TimeStampedModel
        for model in apps.get_models():
            if issubclass(model, TimeStampedModel) and not model._meta.abstract:
                # Register a trigger with a short name (max 47 chars)
                # Use hash of table name to keep it short but unique
                import hashlib

                table_hash = hashlib.md5(model._meta.db_table.encode()).hexdigest()[:8]
                trigger_name = f"upd_mod_{table_hash}"

                try:
                    pgtrigger.register(
                        pgtrigger.Trigger(
                            name=trigger_name,
                            operation=pgtrigger.Update,
                            when=pgtrigger.Before,
                            func="NEW.modified = NOW(); RETURN NEW;",
                        )
                    )(model)
                except KeyError:
                    # Trigger already registered, skip
                    pass
