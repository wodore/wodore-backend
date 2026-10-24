"""SampledCullDatabaseCache — per-write cull-count backport.

Django's ``DatabaseCache`` (up to and including 6.1.x) opens *every* write
(``set``/``add``/``touch``) with ``SELECT COUNT(*) FROM <table>`` to check
``MAX_ENTRIES`` — a full table scan per write on the TOAST-heavy cache
tables (Sentry issue 155299999 grouped the repeated counts on
``/v1/geo/images/hut/{slug}`` as an N+1 pattern; 15–20 ms per span at
staging scale). ``SampledCullDatabaseCache`` backports Django 6.2's
``CULL_PROBABILITY`` gate (upstream ticket #32785): the count runs only on
a sampled fraction of writes.
"""

from uuid import uuid4

import pytest

from django.core import checks
from django.core.cache import caches
from django.core.cache.backends.db import DatabaseCache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from server.core.cache_backends import SampledCullDatabaseCache
from server.core.checks import (
    E001,
    UPSTREAM_FIXED_IN,
    VENDORED_BACKEND_PREFIX,
    _validate,
    check_vendored_cache_backend_removed_on_django_62,
)

#: Private table so row-count assertions never race with other tests'
#: entries in the shared alias tables (the suite runs with --reuse-db).
_TABLE = "django_cache_test_sampled_cull"


def _backend(**options) -> SampledCullDatabaseCache:
    return SampledCullDatabaseCache(_TABLE, {"OPTIONS": options})


@pytest.fixture(autouse=True)
def _fresh_table(db):
    """A clean, test-private cache table for every test."""
    call_command("createcachetable", _TABLE, verbosity=0)
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM "{_TABLE}"')
    yield


def test_configured_aliases_use_sampled_cull_backend():
    """The three DB-backed aliases run the sampled-cull backend.

    (Still DatabaseCache instances, so ``server/core/apps.py`` can hand the
    hut-services alias to the library unchanged.)
    """
    for alias in ("persistent", "hut_services", "shared"):
        backend = caches[alias]
        assert isinstance(backend, SampledCullDatabaseCache), alias
        assert isinstance(backend, DatabaseCache), alias


def test_default_cull_probability_is_upstream_default():
    assert _backend()._cull_probability == 0.1
    assert _backend(MAX_ENTRIES=10)._cull_probability == 0.1


def test_invalid_cull_probability_falls_back():
    assert _backend(CULL_PROBABILITY="bogus")._cull_probability == 0.1


def test_write_skips_cull_count_when_not_sampled():
    """With probability 0 a write never issues SELECT COUNT(*).

    Before the backport, every ``set()`` paid the count: the cold-cache
    /v1/geo/images/hut/{slug} request repeated it for each provider result
    cache and the response envelope (the Sentry N+1 grouping).
    """
    cache = _backend(CULL_PROBABILITY=0)
    key = f"k{uuid4().hex}"

    with CaptureQueriesContext(connection) as ctx:
        cache.set(key, "value", timeout=60)
        cache.get(key)
        cache.touch(key, timeout=120)

    sqls = [q["sql"] for q in ctx.captured_queries]
    assert sqls, "expected queries to be captured"
    assert not any("SELECT COUNT(*)" in sql for sql in sqls)
    # The write still round-trips (keyed SELECT + INSERT, no count).
    assert cache.get(key) == "value"
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{_TABLE}"')
        assert cursor.fetchone()[0] == 1


def test_cull_check_runs_when_sampled():
    """With probability 1 the upstream cull check (COUNT) is back."""
    cache = _backend(CULL_PROBABILITY=1)
    key = f"k{uuid4().hex}"

    with CaptureQueriesContext(connection) as ctx:
        cache.set(key, "value", timeout=60)

    sqls = [q["sql"] for q in ctx.captured_queries]
    assert any("SELECT COUNT(*)" in sql for sql in sqls)
    assert cache.get(key) == "value"


def test_culling_still_enforced_when_sampled():
    """MAX_ENTRIES/CULL_FREQUENCY semantics survive the sampling gate."""
    cache = _backend(CULL_PROBABILITY=1, MAX_ENTRIES=5, CULL_FREQUENCY=2)
    for i in range(7):
        cache.set(f"k{i}", i, timeout=300)

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{_TABLE}"')
        count = cursor.fetchone()[0]

    # The count runs before each insert (strict num > MAX_ENTRIES), so
    # writes 1-6 fill the table without culling; write 7 sees num=6 > 5,
    # culls 6 // CULL_FREQUENCY = 3 oldest (k0-k2), then inserts k6:
    # 6 - 3 + 1 = 4 rows remain.
    assert count == 4


# --- Removal enforcement (core.E001) --------------------------------------
#
# The backport must not outlive Django 6.1: once Django ships
# CULL_PROBABILITY natively, a startup check blocks the wired aliases
# until the module is deleted (see server/core/checks.py).


def _current_aliases_config() -> dict:
    from django.conf import settings

    return {a: dict(c) for a, c in settings.CACHES.items()}


def test_check_silent_before_django_62():
    """Pre-6.2 (today) the vendored wiring is the intended state."""
    assert UPSTREAM_FIXED_IN > (6, 1), (  # type: ignore  # literal tuple comparison in test
        "project is on Django 6.1.x — adjust this test with the removal"
    )
    errors = _validate(_current_aliases_config(), (6, 1, 5, "final", 0))
    assert errors == []


def test_check_blocks_vendored_backend_on_django_62():
    """On >= 6.2 the wired backport fails startup with removal steps."""
    errors = _validate(_current_aliases_config(), (6, 2, 0, "final", 0))
    assert len(errors) == 1
    error = errors[0]
    assert error.id == E001
    assert isinstance(error, checks.Error)
    assert "persistent" in error.msg and "hut_services" in error.msg
    assert VENDORED_BACKEND_PREFIX in (error.hint or "")


def test_check_passes_on_django_62_after_removal():
    """Post-removal state (plain DatabaseCache) is clean on >= 6.2."""
    config = _current_aliases_config()
    for alias in ("persistent", "hut_services", "shared"):
        config[alias]["BACKEND"] = "django.core.cache.backends.db.DatabaseCache"
    assert _validate(config, (6, 2, 0, "final", 0)) == []
    assert _validate(config, (7, 0, 0, "final", 0)) == []


def test_registered_check_quiet_under_current_django():
    """The registered system check is silent on the installed 6.1.x."""
    errors = check_vendored_cache_backend_removed_on_django_62()
    assert errors == []
