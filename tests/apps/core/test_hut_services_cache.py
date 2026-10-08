"""hut-services cache backend wiring.

hut-services' built-in default backend writes pickles to
``<tempdir>/py_file_cache``. ``server/core/apps.py`` wires the Django
``hut_services`` cache alias (``DatabaseCache``) as the library's backend
instead, so external-service responses live in the database: shared across
workers, surviving restarts, and with no file-cache writes.
"""

from pathlib import Path
from uuid import uuid4

from django.core.cache import caches
from django.core.cache.backends.db import DatabaseCache
from django.db import connection


def test_hut_services_alias_is_database_backed():
    """The alias handed to hut-services must be a database cache."""
    assert isinstance(caches["hut_services"], DatabaseCache)


def test_default_backend_wired_to_django_alias():
    """``ready()`` replaced the library's file backend with our alias."""
    from hut_services.core.cache import FileCacheBackend, get_default_cache_backend

    backend = get_default_cache_backend()
    assert not isinstance(backend, FileCacheBackend)
    assert backend is caches["hut_services"]


def test_cached_function_uses_db_table_not_filesystem(db):
    """A ``@cached`` function round-trips through the DB cache table only."""
    from hut_services.core.cache import cached

    file_cache_dir = Path(__import__("tempfile").gettempdir()) / "py_file_cache"

    def file_cache_files():
        # The library creates an empty directory at import time; cache
        # entries would be files below it. Tolerate files other (unwired)
        # processes left behind and only assert this run adds none.
        return (
            {p for p in file_cache_dir.rglob("*") if p.is_file()}
            if file_cache_dir.exists()
            else set()
        )

    calls = []

    @cached(expire_in_seconds=60)
    def square(x: int) -> int:
        calls.append(x)
        return x * x

    # Unique argument per run: entries survive in the reused test database
    # and cache keys are argument-derived, so a fixed value would collide
    # with a previous session's row.
    x = uuid4().int % 10**9
    files_before = file_cache_files()

    assert square(x) == x * x
    assert square(x) == x * x
    assert calls == [x]  # second call was served from the cache

    square.evict(x)
    assert square(x) == x * x
    assert calls == [x, x]  # evicted -> recomputed via backend delete()

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_cache_hut_services")
        assert cursor.fetchone()[0] >= 1

    assert file_cache_files() == files_before
