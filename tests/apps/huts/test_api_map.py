"""Tests for the static map endpoint and the og map card URL.

Tile fetching is monkeypatched (no network in tests); MEDIA_ROOT is
redirected to a tmp dir so no rendered PNGs leak into the repo.
"""

import pytest

from server.apps.api import ogmap
from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def tile_fetch(monkeypatch):
    """Fake tiles: solid color varying by position (visible in tests)."""
    from PIL import Image

    calls = []

    def fake_fetch(zoom, x, y):
        calls.append((zoom, x, y))
        color = (40 + (x * 13) % 100, 60 + (y * 17) % 100, 120)
        return Image.new("RGB", (ogmap.TILE_SIZE, ogmap.TILE_SIZE), color)

    monkeypatch.setattr(ogmap, "_fetch_tile", fake_fetch)
    return calls


class TestHutMapEndpoint:
    def test_map_png(self, seed_data, client, tile_fetch):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}/map.png")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"
        assert len(response.content) > 1000
        assert "public, max-age=" in response.headers["Cache-Control"]

    def test_rendered_once_then_served_from_storage(
        self, seed_data, client, tile_fetch
    ):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}/map.png").status_code == 200
        tiles_first = len(tile_fetch)
        assert tiles_first > 0
        assert client.get(f"/v1/huts/{hut.slug}/map.png").status_code == 200
        assert len(tile_fetch) == tiles_first  # served from storage, no re-fetch

    def test_change_busts_storage(self, seed_data, client, tile_fetch):
        """Any hut change (modified bump) renders a new map file."""
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        assert client.get(f"/v1/huts/{hut.slug}/map.png").status_code == 200
        tiles_first = len(tile_fetch)
        hut.name = f"{hut.name} changed"
        hut.save()  # bumps modified
        assert client.get(f"/v1/huts/{hut.slug}/map.png").status_code == 200
        assert len(tile_fetch) > tiles_first

    def test_unknown_slug_404(self, seed_data, client, tile_fetch):
        assert client.get("/v1/huts/nope-xyz/map.png").status_code == 404

    def test_hidden_hut_404(self, seed_data, client, tile_fetch):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        hut.is_public = False
        hut.save()
        assert client.get(f"/v1/huts/{hut.slug}/map.png").status_code == 404


class TestMetaMapFallback:
    def test_no_photo_uses_static_map_card(
        self, seed_data, client, settings, tile_fetch
    ):
        """Fallback chain: no photo -> static map card with version param."""
        from django.core.cache import cache

        cache.clear()
        settings.FRONTEND_DOMAIN = "https://wodore.com"
        from server.apps.huts.models import HutImageAssociation

        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert "map.png" in data["image"]
        # '=' is percent-encoded inside the imagor source URL
        assert f"v%3D{hut.modified:%Y%m%dT%H%M%S}" in data["image"]
        assert "0.18" in data["image"]  # watermark left
