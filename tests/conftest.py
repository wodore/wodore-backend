"""Shared test configuration.

``DJANGO_ENV`` is pinned in two places: ``server/settings/__init__.py``
guards the pytest case directly (pytest-django builds settings before any
conftest code runs), and the module-level ``setdefault`` below covers
non-standard settings modules that might not go through that guard.
"""

import hashlib
import os

os.environ.setdefault("DJANGO_ENV", "test")

import pytest

from server.apps.huts.models import Hut


def _reset_pk_sequences() -> None:
    """Advance Postgres pk sequences past fixture-loaded explicit ids.

    Fixture files (e.g. organizations.yaml) carry explicit ``pk:``
    values; loading them does not advance the sequences, so later
    factory/ORM inserts collide with existing ids (duplicate key
    violations - seen live in CI and on staging). Idempotent.
    """
    from django.apps import apps
    from django.db import connection

    qn = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in apps.get_models():
            field = model._meta.auto_field
            if field is None:
                continue
            table = model._meta.db_table
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)", [table, field.column]
            )
            seq = cursor.fetchone()[0]
            if not seq:
                continue
            cursor.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX({qn(field.column)})"
                f" FROM {qn(table)}), 0) + 1, false)",
                [seq],
            )


_pk_sequences_reset_done = False


@pytest.fixture(autouse=True)
def _pk_sequences_reset(request, django_db_blocker):
    """Advance pk sequences past fixture-loaded explicit ids before the first db test.

    Test order must not matter: with pytest-randomly shuffling, unseeded
    tests can run before ``seed_data``; on a reused database that already
    carries explicit-pk rows (CI's cached pgdata, staging snapshots), a
    factory insert then collides (UniqueViolation on
    ``organizations_organization_pkey`` - seen live in CI, PR #270 run
    37381918302). This autouse fixture applies to every test regardless
    of fixtures; the reset itself runs once per session, which is
    sufficient: sequences only ever move forward within a session
    (nextval survives rollback, flush never rewinds), and the one op that
    pushes sequences behind explicit pks - seed loading - re-resets via
    ``seed_data`` itself.

    Tests without any database marker/fixture are skipped untouched, so
    database creation is never forced for pure unit tests.
    """
    global _pk_sequences_reset_done
    uses_db = (
        request.node.get_closest_marker("django_db") is not None
        or "db" in request.fixturenames
        or "transactional_db" in request.fixturenames
    )
    if _pk_sequences_reset_done or not uses_db:
        return
    request.getfixturevalue("db")  # ensure setup and an unblocked window
    with django_db_blocker.unblock():
        _reset_pk_sequences()
        _pk_sequences_reset_done = True


def _seed_file_hash() -> str:
    """Compute a hash of all seed YAML files to detect changes."""
    from tests.seed.loader import SEED_DIR

    hasher = hashlib.md5()
    for seed_file in sorted(SEED_DIR.glob("*.yaml")):
        hasher.update(seed_file.read_bytes())
    return hasher.hexdigest()


@pytest.fixture(scope="session")
def seed_data(django_db_setup, django_db_blocker):
    """Session-scoped fixture that loads seed data once per test session.

    Detects if seeding is needed:
    - No huts in the database (first run or --create-db)
    - Seed file content has changed (hash comparison)
    """
    from tests.seed.loader import load_all_seeds

    with django_db_blocker.unblock():
        needs_seeding = False

        if not Hut.objects.exists():
            needs_seeding = True
        else:
            # Check if seed files have changed since last seed
            from django.core.cache import cache

            cached_hash = cache.get("test_seed_hash")
            current_hash = _seed_file_hash()
            if cached_hash != current_hash:
                needs_seeding = True

        if needs_seeding:
            # Clear existing seed data before re-seeding to avoid
            # duplicate key errors when --reuse-db is active.
            Hut.objects.all().delete()

            results = load_all_seeds()
            # Store hash to detect future changes
            from django.core.cache import cache

            cache.set("test_seed_hash", _seed_file_hash())
        else:
            results = {}

        # App fixtures load with explicit pks and leave sequences behind
        # (management base); reset on every session regardless of whether
        # seeds were (re)loaded. Must run inside the unblocked context.
        _reset_pk_sequences()

    return results
