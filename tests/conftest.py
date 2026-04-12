import hashlib
import os

import pytest

from server.apps.huts.models import Hut


def pytest_configure(config):
    os.environ.setdefault("DJANGO_ENV", "test")


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
            results = load_all_seeds()
            # Store hash to detect future changes
            from django.core.cache import cache

            cache.set("test_seed_hash", _seed_file_hash())
            return results

    return {}
