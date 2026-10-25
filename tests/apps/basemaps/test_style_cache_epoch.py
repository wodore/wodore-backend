"""Registry edits re-key rendered style bodies (epoch bump).

Rendered style bodies bake registry values in at render time — the tile
origin via ``{TILE_SERVER_URL}`` absolutization, ``{{env:...}}`` tokens
via substitution. The body cache is version-keyed (modified + asset
digest + registry epoch); an env-registry edit bumps the epoch via the
``post_save``/``post_delete`` signal wiring, so no cached body survives
a registry change with stale baked-in values (review finding #1: the
7-day ``STYLE_CACHE_TTL`` would otherwise hide an admin override).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from django.core.cache import cache

from server.apps.basemaps.api import (
    STYLE_BODIES_EPOCH_KEY,
    _registry_changed,
    _style_cache_get,
    _style_cache_key,
    _style_cache_set,
)
from server.apps.basemaps.models import MapLayer
from server.apps.envvars.models import EnvVar


@pytest.fixture(autouse=True)
def _clean_epoch():
    """Fresh epoch + no seeded rows.

    The default cache is database-backed in tests, and migration 0004
    seeds the URL-origin rows — wipe them (the post_delete signal bumps
    the epoch, hence the reset afterwards).
    """
    EnvVar.objects.all().delete()
    cache.delete(STYLE_BODIES_EPOCH_KEY)
    yield
    cache.delete(STYLE_BODIES_EPOCH_KEY)


def _layer() -> MapLayer:
    """An unsaved layer — cache keys read pk/spec/modified, no DB row."""
    layer = MapLayer(pk=1, slug="test-layer", spec="high")
    layer.modified = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    return layer


@pytest.mark.django_db
class TestEpochBump:
    def test_registry_changed_bumps_epoch(self):
        _registry_changed()
        assert cache.get(STYLE_BODIES_EPOCH_KEY) == 1
        _registry_changed()
        assert cache.get(STYLE_BODIES_EPOCH_KEY) == 2

    @pytest.mark.django_db
    def test_envvar_save_fires_signal_and_bumps_epoch(self):
        """The real wiring: post_save on EnvVar → ``_registry_changed``."""
        assert cache.get(STYLE_BODIES_EPOCH_KEY) is None
        EnvVar.objects.create(name="MARTIN_TILE_URL", value="https://cdn.example.org")
        assert cache.get(STYLE_BODIES_EPOCH_KEY) == 1


@pytest.mark.django_db
class TestKeyRotation:
    def test_registry_change_rekeys_style_cache(self):
        layer = _layer()
        _style_cache_set(layer, tokenized=False, body="[]", etag='"x"', digest="d")
        assert _style_cache_get(layer, tokenized=False, digest="d") == ("[]", '"x"')

        _registry_changed()  # operator edits a registry row

        # Old entry unreachable — the next render is a miss and re-bakes
        # the (changed) tile origin / env tokens.
        assert _style_cache_get(layer, tokenized=False, digest="d") is None

    def test_epoch_is_part_of_the_key(self):
        layer = _layer()
        before = _style_cache_key(layer, tokenized=False, digest="d")
        _registry_changed()
        after = _style_cache_key(layer, tokenized=False, digest="d")
        assert before != after
        assert after.endswith(":1")
