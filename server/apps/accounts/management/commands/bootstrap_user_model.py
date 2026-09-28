"""One-off surgery for switching AUTH_USER_MODEL on an existing database.

Changing ``AUTH_USER_MODEL`` makes already-applied migrations that used
``swappable_dependency`` (admin, allauth, oauth2_provider, images, …)
depend on ``accounts.0001_initial`` at load time — so ``migrate`` refuses
to run on databases created before the switch ("InconsistentMigrationHistory").

This command is idempotent and safe on fresh databases too:

- detects the situation (``admin.0001_initial`` applied, ``accounts.0001``
  not) and if so: applies ``accounts.0001_initial`` through Django's
  migration machinery out of band (table creation + the auth-user copy),
  then records it in ``django_migrations``;
- afterwards (or immediately on fresh databases) runs ``migrate`` normally.

Run once per existing database (dev main DB, wodore_template, lanes).
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Bootstrap the custom user model switch on pre-switch databases."

    def handle(self, *args: Any, **options: Any) -> None:
        from django.core.management import call_command

        applied = self._applied_migrations()
        needs_surgery = ("admin", "0001_initial") in applied and (
            "accounts",
            "0001_initial",
        ) not in applied
        fresh = not applied

        if fresh:
            self.stdout.write("Fresh database - plain migrate orders correctly.")
        elif needs_surgery:
            self._apply_initial_out_of_band()
        elif ("accounts", "0001_initial") in applied:
            self.stdout.write(
                "accounts.0001_initial already applied - nothing to bootstrap."
            )

        call_command("migrate", interactive=False)

    # -- helpers -------------------------------------------------------------

    def _applied_migrations(self) -> set[tuple[str, str]]:
        if "django_migrations" not in connection.introspection.table_names():
            return set()
        with connection.cursor() as cursor:
            cursor.execute("SELECT app, name FROM django_migrations")
            return {(app, name) for app, name in cursor.fetchall()}

    def _apply_initial_out_of_band(self) -> None:
        """Apply accounts.0001_initial manually, then record it as applied.

        Uses the migration's own operations through Django's schema editor
        (same code path ``migrate`` would use), bypassing only the loader's
        consistency check that would refuse the out-of-order dependency.
        """
        from django.db.migrations.loader import MigrationLoader

        self.stdout.write(
            "Pre-switch database detected - bootstrapping accounts.0001_initial…"
        )

        loader = MigrationLoader(connection, replace_migrations=False)
        migration = loader.get_migration("accounts", "0001_initial")

        # Base state: everything the migration's dependencies provide
        # (contenttypes + auth models), WITHOUT auth.User being swapped.
        # project_state() of the dependency node gives exactly that.
        dep_node = migration.dependencies[0]  # ('auth', '0012_…')
        state = loader.project_state(dep_node)

        with connection.schema_editor() as editor:
            migration.apply(state, editor)

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO django_migrations (app, name, applied) "
                "VALUES (%s, %s, %s)",
                ["accounts", "0001_initial", timezone.now()],
            )
        self.stdout.write(
            self.style.SUCCESS(
                "accounts.0001_initial bootstrapped (users copied, pks kept)."
            )
        )
