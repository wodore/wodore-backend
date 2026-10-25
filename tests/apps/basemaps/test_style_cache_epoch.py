"""Registry edits re-key rendered style bodies (DB-derived epoch).

Rendered style bodies bake registry values in at render time — the tile
origin via ``{TILE_SERVER_URL}`` absolutization, ``{{env:...}}`` tokens
via substitution. The body cache is version-keyed (modified + asset
digest + registry epoch); the epoch is DERIVED from the EnvVar table
(count + max(modified)) and memoized 10 s — never signal-bumped, because
the default cache is process-local (LocMemCache) and a bump would never
reach the other gunicorn workers. Every worker derives the identical
epoch from the DB and converges within the memo window (review finding:
a signal-bumped epoch left N−1 workers serving stale origins for up to
the 7-day ``STYLE_CACHE_TTL``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client

from server.apps.basemaps.api import (
    STYLE_BODIES_EPOCH_KEY,
    _registry_changed,
    _style_bodies_epoch,
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
    seeds the URL-origin rows — wipe them (the signals fire, hence the
    memo reset afterwards).
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
class TestDerivedEpoch:
    def test_epoch_tracks_registry_state(self):
        epoch_empty = _style_bodies_epoch()
        EnvVar.objects.create(name="A_TEST_KEY", value="1")
        cache.delete(STYLE_BODIES_EPOCH_KEY)
        assert _style_bodies_epoch() != epoch_empty  # count changed

    def test_workers_derive_identical_epoch(self):
        """Cross-process proof: the epoch is a function of DB state, not
        of any in-process signal — two independent memos agree."""
        EnvVar.objects.create(name="A_TEST_KEY", value="1")
        cache.delete(STYLE_BODIES_EPOCH_KEY)
        first = _style_bodies_epoch()
        cache.delete(STYLE_BODIES_EPOCH_KEY)  # "the other worker"
        assert _style_bodies_epoch() == first

    def test_memo_serves_within_ttl(self):
        cache.set(STYLE_BODIES_EPOCH_KEY, "stale-memo")
        assert _style_bodies_epoch() == "stale-memo"

    def test_registry_changed_clears_memo(self):
        cache.set(STYLE_BODIES_EPOCH_KEY, "stale-memo")
        _registry_changed()
        assert cache.get(STYLE_BODIES_EPOCH_KEY) is None

    def test_envvar_save_fires_signal_and_clears_memo(self):
        """The real wiring: post_save on EnvVar → ``_registry_changed``."""
        cache.set(STYLE_BODIES_EPOCH_KEY, "stale-memo")
        EnvVar.objects.create(name="MARTIN_TILE_URL", value="https://cdn.example.org")
        assert cache.get(STYLE_BODIES_EPOCH_KEY) is None


@pytest.mark.django_db
class TestKeyRotation:
    def test_registry_change_rekeys_style_cache(self):
        layer = _layer()
        _style_cache_set(layer, tokenized=False, body="[]", etag='"x"', digest="d")
        assert _style_cache_get(layer, tokenized=False, digest="d") == ("[]", '"x"')

        EnvVar.objects.create(name="MARTIN_TILE_URL", value="https://cdn.example.org")

        # Signal cleared the memo; the next derivation sees the new DB
        # state → old entry unreachable, the next render re-bakes.
        assert _style_cache_get(layer, tokenized=False, digest="d") is None

    def test_pinned_epoch_pins_the_key(self):
        """One epoch per request: a registry edit landing mid-request
        cannot file a pre-edit body under the post-edit epoch."""
        layer = _layer()
        key = _style_cache_key(layer, tokenized=False, digest="d", epoch="pinned")
        assert key.endswith(":d:pinned")
        _style_cache_set(
            layer, tokenized=False, body="[]", etag='"x"', digest="d", epoch="pinned"
        )
        assert _style_cache_get(layer, tokenized=False, digest="d", epoch="pinned") == (
            "[]",
            '"x"',
        )


@pytest.mark.django_db
class TestServePathRotation:
    """End-to-end through the HTTP serve path (the collected-suite gap
    the review flagged): a registry edit rotates origin and ETag."""

    def test_registry_edit_rotates_served_origin_and_etag(self):
        call_command("map_seed", verbosity=0)
        client = Client()

        first = client.get("/v1/map/styles/huts.json")
        assert first.status_code == 200
        assert "https://tiles.cdn.example.org" not in json.dumps(first.json())

        # Operator stores a tile-origin override in the admin.
        EnvVar.objects.update_or_create(
            name="MARTIN_TILE_URL",
            defaults={"value": "https://tiles.cdn.example.org"},
        )

        second = client.get("/v1/map/styles/huts.json")
        assert second.status_code == 200
        assert "https://tiles.cdn.example.org" in json.dumps(second.json())
        assert second.headers["ETag"] != first.headers["ETag"]
