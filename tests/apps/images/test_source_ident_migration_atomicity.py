"""Images migrations 0033/0034 must apply in separate transactions — the
BACKEND-DJANGO-8 staging deploy regression.

0033 as shipped combined the dedupe RunPython and the partial unique
constraint (``CREATE UNIQUE INDEX``) in one atomic migration — one
transaction. Django creates foreign keys as ``DEFERRABLE INITIALLY
DEFERRED``, so the dedupe DML queues FK-check trigger events that only
fire at COMMIT, and Postgres refuses index builds over pending trigger
events: the staging migrate job died with ``cannot CREATE INDEX
"images_image" because it has pending trigger events`` (release d3bdc2bc,
wd-backend-migrate). The fix keeps the constraint in its own migration
(0034); this test drives 0033 + 0034 through the real MigrationExecutor
with twins present — one transaction per migration, exactly like
``manage.py migrate``. Re-merging the operations into one migration makes
it fail with the exact staging error.

This lives in its own module, unmarked by ``django_db``: the executor's
operations must run in REAL committed transactions, not inside the
per-test wrapping atom (a wrapping transaction would re-create the very
same-tx DML+DDL overlap this regression forbids). ``django_db(transaction=
True)`` is no alternative — its TransactionTestCase flush wipes
migration-seeded data (e.g. the symbols ``activities`` curated list) for
every module that runs afterwards. Instead the test runs under
``django_db_blocker.unblock()`` with explicit cleanup, the same pattern
the dedupe module's ``legacy_schema`` fixture uses for its DDL.

The merge-logic behaviour itself (keeper choice, association re-pointing,
tag adoption) is covered in ``test_source_ident_dedupe_migration.py``.
"""

from datetime import UTC, datetime

import pytest
from pytest_django.plugin import DjangoDbBlocker

from server.apps.images.models import Image
from server.apps.licenses.models import License

CONSTRAINT_NAME = "images_image_source_ident_unique"
IDENT = "wikicommons:File:Cedullo.jpg"
MIGRATION_NAMES = (
    "0033_merge_duplicate_pins_unique_source_ident",
    "0034_image_source_ident_unique",
)


def _constraint():
    return next(
        constraint
        for constraint in Image._meta.constraints
        if constraint.name == CONSTRAINT_NAME
    )


@pytest.fixture(scope="module", autouse=True)
def legacy_schema(django_db_setup: None, django_db_blocker: DjangoDbBlocker):
    """Pre-0034 schema for the whole module: no source_ident uniqueness.

    The teardown re-adds the constraint, so the shared test DB stays in
    its fully-migrated shape for later modules and sessions.
    """
    from django.db import connection

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.remove_constraint(Image, _constraint())
    yield
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.add_constraint(Image, _constraint())


class TestMigrationsApplySeparately:
    def test_executor_applies_data_then_constraint(
        self, django_db_blocker: DjangoDbBlocker
    ):
        from django.db import IntegrityError, connection
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.recorder import MigrationRecorder

        with django_db_blocker.unblock():  # real, committed transactions
            license_obj = License.objects.get_or_create(
                slug="dedupe-migration-regression", defaults={"no_publication": False}
            )[0]
            Image.objects.create(
                source_ident=IDENT,
                license=license_obj,
                created=datetime(2026, 1, 1, tzinfo=UTC),
            )
            Image.objects.create(  # the twin a concurrent sync minted
                source_ident=IDENT,
                license=license_obj,
                created=datetime(2026, 1, 2, tzinfo=UTC),
            )

            # Roll the recorder back to pre-0033 so the executor replays
            # both migrations for real (schema-wise the constraint is
            # already gone — legacy_schema dropped it).
            recorder = MigrationRecorder(connection)
            recorder.migration_qs.filter(
                app="images", name__in=MIGRATION_NAMES
            ).delete()
            try:
                executor = MigrationExecutor(connection)
                executor.migrate([("images", MIGRATION_NAMES[1])])

                # Data half merged the twins in its own transaction ...
                assert Image.objects.filter(source_ident=IDENT).count() == 1
                # ... and the constraint half built cleanly in the next.
                with pytest.raises(IntegrityError):
                    Image.objects.create(source_ident=IDENT, license=license_obj)
            finally:
                # pytest-django reuses the test DB across sessions — leave
                # it consistent even on failure, or later sessions die on
                # "already exists": recorder rows back, constraint dropped
                # (legacy_schema's teardown re-adds it), seed rows removed.
                recorded = set(
                    recorder.migration_qs.filter(
                        app="images", name__in=MIGRATION_NAMES
                    ).values_list("name", flat=True)
                )
                for name in MIGRATION_NAMES:
                    if name not in recorded:
                        recorder.record_applied("images", name)
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(
                        cursor, "images_image"
                    )
                if CONSTRAINT_NAME in constraints:
                    with connection.schema_editor() as editor:
                        editor.remove_constraint(Image, _constraint())
                Image.objects.filter(source_ident=IDENT).delete()
                License.objects.filter(slug="dedupe-migration-regression").delete()
