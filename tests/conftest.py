"""Shared test configuration.

``DJANGO_ENV`` is pinned in two places: ``server/settings/__init__.py``
guards the pytest case directly (pytest-django builds settings before any
conftest code runs), and the module-level ``setdefault`` below covers
non-standard settings modules that might not go through that guard.
"""

import os
from typing import Any

os.environ.setdefault("DJANGO_ENV", "test")

import pytest
from pytest_django.plugin import DjangoDbBlocker

from tests.seed.loader import (
    load_all_seeds,
    reset_pk_sequences,
    restore_post_flush,
    seed_file_hash,
)

from server.apps.huts.models import Hut


@pytest.fixture(autouse=True, scope="session")
def _bake_root_urlconf():
    """Import the root urlconf eagerly (session start, real settings).

    ``server/urls.py`` generates the per-language ``/llms.<lang>.txt``
    routes from ``settings.LANGUAGES``, and a urlconf is imported lazily
    on the first URL resolution of the process. Under pytest-randomly
    that first resolution can happen inside a test overriding
    ``settings.LANGUAGES`` — the overridden routes then stay baked into
    the session-wide resolver and order-dependently break other tests
    (seen with the llms.txt variants). Importing the urlconf here, before
    any test runs, pins it to the real settings; per-test overrides
    route through the settings-driven view logic instead.
    """
    import server.urls  # noqa: F401  (import for its side effect)


def _reset_pk_sequences() -> None:
    """Advance Postgres pk sequences past fixture-loaded explicit ids."""
    reset_pk_sequences()


_pk_sequences_reset_done = False


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> Any:
    """Force every transactional test onto Django's serialized rollback.

    ``django_db(transaction=True)`` tests tear down with a database
    flush that destroys data-migration rows and seed data (see
    ``loader.restore_post_flush``). Django's ``serialized_rollback``
    machinery snapshots the pristine post-migrate database at test-db
    setup (``connection._test_serialized_contents``) — but only when at
    least one test requests it. Wiring EVERY transactional test onto it
    guarantees the snapshot exists exactly when flushes can happen, and
    the transactional tests themselves start from a restored baseline.
    """
    from pytest import Mark, MarkDecorator

    for item in items:
        fixturenames = getattr(item, "fixturenames", None)
        marker = item.get_closest_marker("django_db")
        transactional_marker = marker is not None and (
            marker.kwargs.get("transaction") or marker.kwargs.get("reset_sequences")
        )
        fixture_routed = fixturenames is not None and (
            "transactional_db" in fixturenames or "live_server" in fixturenames
        )
        if transactional_marker:
            assert marker is not None  # narrowed by transactional_marker
            # The marker usually lives on the CLASS (``own_markers`` of
            # the item stays empty — items inherit class markers through
            # ``iter_markers``), so rewriting it in place is a no-op.
            # An ITEM-level marker shadows it for get_closest_marker —
            # which is what pytest-django reads both at session setup
            # (_get_databases_for_setup → serialized_aliases) and at
            # test setup (_django_db_helper).
            item.add_marker(
                MarkDecorator(
                    Mark(
                        marker.name,
                        marker.args,
                        {**marker.kwargs, "serialized_rollback": True},
                        _ispytest=True,
                    ),
                    _ispytest=True,
                )
            )
        elif fixture_routed:
            # Fixture-routed transactional test (no django_db marker):
            # the django_db_serialized_rollback fixture is the only
            # opt-in pytest-django reads for this shape.
            assert fixturenames is not None  # narrowed by fixture_routed
            fixturenames.append("django_db_serialized_rollback")
        else:
            continue
        # Request the end-of-session repair for every session that has
        # transactional tests (the only sessions whose flushes can gut
        # the database CI caches and reuses). PREPENDED so it sets up
        # before the db fixtures — when a later fixture errors at setup
        # (a failing test run), already-set-up fixtures still tear down
        # and the repair still runs; appended-last it would never be
        # reached and the session would end gutted.
        if fixturenames is not None and "_healthy_db_at_exit" not in fixturenames:
            fixturenames.insert(0, "_healthy_db_at_exit")
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Any:
    """Restore the flushed-database baseline before fixture setup.

    Must run BEFORE pytest-django's ``db``/``transactional_db`` fixtures
    enter their atomics: the restore commits, so data written here is
    visible to *other connections* — the ASGI tests drive the app from
    request threads, and the reviews provider tests run sync code on
    worker threads; neither can see rows inside the test's uncommitted
    transaction. An autouse fixture would lose that race against the
    plugin's own autouse ordering; a setup hook cannot.
    """
    _restore_flushed_baseline(item)
    yield


def _restore_flushed_baseline(item: pytest.Item) -> None:
    """Detect and repair transactional-test flushes (see loader.restore_post_flush).

    Runs only for tests that use the database — pure unit tests must
    never force test-database creation. Guarded against db errors:
    before the session's first db test the test database does not exist
    yet (``django_db_setup`` creates it during fixture setup — the
    connection then either fails to connect, or points at an
    un-migrated database), and nothing can have been flushed at that
    point anyway.
    """
    from pytest import Function
    from pytest_django.plugin import blocking_manager_key

    from django.db import OperationalError, ProgrammingError

    fixturenames = item.fixturenames if isinstance(item, Function) else []
    uses_db = (
        item.get_closest_marker("django_db") is not None
        or "db" in fixturenames
        or "transactional_db" in fixturenames
    )
    if not uses_db:
        return
    try:
        with item.config.stash[blocking_manager_key].unblock():
            restore_post_flush()
    except (OperationalError, ProgrammingError):
        pass  # test database not set up yet — nothing to restore


@pytest.fixture(scope="session")
def _healthy_db_at_exit(
    django_db_setup: None,  # pytest fixture dep (resolved by name)
    django_db_blocker: DjangoDbBlocker,
):
    """Leave the test database healthy when the session ends.

    A session whose last test was transactional ends on a flushed (empty
    vocabulary) database. CI caches that pgdata and the next run reuses
    it — it would start from a gutted baseline that ``migrate`` cannot
    repair (data migrations are already recorded) and snapshot. This
    fixture is requested (via the collection hook) by every
    transactional test, so it finalizes — before ``django_db_setup``
    tears the test-database context down — exactly for the sessions
    that can end gutted. It restores the baseline from the snapshot and
    then clears the seed rows so the next session's snapshot (taken
    from the reused database) stays seed-free — stale seed rows in a
    snapshot collide with re-loaded seeds (see loader.clear_seed_rows).
    """
    from tests.seed.loader import clear_seed_rows

    from django.db import Error as DbError

    yield
    try:
        with django_db_blocker.unblock():
            restore_post_flush()
            clear_seed_rows()
    except DbError:
        pass  # test database vanished mid-session — nothing to restore


@pytest.fixture(autouse=True)
def _clear_geoplace_caches():
    """Clear GeoPlace's process-wide lru caches before every test.

    ``_resolve_category_from_identifier`` and ``_get_organization_by_slug"
    cache across tests; stale entries from rolled-back transactions poison
    subsequent tests regardless of module (kind-guard validation rejects
    valid classifiers when a root-level category was cached for an
    identifier that now resolves to an accommodation child).
    """
    from server.apps.geometries.models import GeoPlace

    GeoPlace._resolve_category_from_identifier.cache_clear()
    GeoPlace._get_organization_by_slug.cache_clear()


@pytest.fixture(autouse=True)
def _pk_sequences_reset(
    request: pytest.FixtureRequest, django_db_blocker: DjangoDbBlocker
):
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
    return seed_file_hash()


@pytest.fixture(scope="session")
def seed_data(django_db_setup: None, django_db_blocker: DjangoDbBlocker):
    """Session-scoped fixture that loads seed data once per test session.

    Detects if seeding is needed:
    - No huts in the database (first run or --create-db)
    - Seed file content has changed (hash comparison)
    """
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
            results: dict[str, int] = {}

        # App fixtures load with explicit pks and leave sequences behind
        # (management base); reset on every session regardless of whether
        # seeds were (re)loaded. Must run inside the unblocked context.
        _reset_pk_sequences()

    return results
