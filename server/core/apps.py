"""
Core app configuration.
"""

import pgtrigger
import structlog

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

                # Postgres identifier limit (63) - non-security identifier
                # hashing of the table name (see usedforsecurity=False).
                table_hash = hashlib.new(
                    "md5", model._meta.db_table.encode(), usedforsecurity=False
                ).hexdigest()[:8]
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

        # hut-services: replace the library's default file cache (pickles
        # under <tempdir>/py_file_cache) with the Django database cache.
        # Its CacheBackend protocol matches BaseCache as-is, so the cache is
        # injected as-is (hut-services docs/caching.md). Wired in ready() -
        # after apps load, never at import time - because the ``cached``
        # wrapper resolves the backend on every call.
        # Only wire when the configured alias actually is database-backed;
        # otherwise the library would silently keep writing files.
        from typing import cast

        from hut_services.core.cache import CacheBackend, set_default_cache_backend

        from django.core.cache import caches
        from django.core.cache.backends.db import DatabaseCache

        hut_services_cache = caches["hut_services"]
        if isinstance(hut_services_cache, DatabaseCache):
            # Runtime-conformant: BaseCache implements CacheBackend as-is
            # (hut-services docs). The cast only bridges pyright rejecting
            # Django's ``delete() -> bool`` against the protocol's declared
            # ``delete() -> None`` (the return value is discarded).
            set_default_cache_backend(cast(CacheBackend, hut_services_cache))
        else:
            structlog.get_logger("server.core").warning(
                "hut_services cache alias is not DatabaseCache (%s) - "
                "hut-services falls back to its file cache backend",
                type(hut_services_cache).__name__,
            )
