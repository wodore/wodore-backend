"""Tests for the generic static-map endpoint (/v1/geo/map/static).

Tile fetching and the marker/watermark fetchers are monkeypatched (no
network in tests); MEDIA_ROOT is redirected to a tmp dir.
"""

import pytest

from server.apps.api import ogmap
from server.apps.geometries.models import GeoPlace
from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def offline_render(monkeypatch):
    """Fake tiles, marker and watermark (no network)."""
    from PIL import Image

    calls = {"tiles": 0, "marker": 0, "watermark": 0}

    def fake_tile(zoom, x, y):
        calls["tiles"] += 1
        return Image.new("RGB", (ogmap.TILE_SIZE, ogmap.TILE_SIZE), (90, 120, 150))

    def fake_marker(symbol_url, size_px):
        calls["marker"] += 1
        return Image.new("RGBA", (size_px, size_px), (200, 60, 60, 255))

    def fake_watermark():
        calls["watermark"] += 1
        return Image.new("RGBA", (300, 300), (20, 60, 40, 255))

    monkeypatch.setattr(ogmap, "_fetch_tile", fake_tile)
    monkeypatch.setattr(ogmap, "fetch_marker", fake_marker)
    monkeypatch.setattr(ogmap, "fetch_watermark", fake_watermark)
    return calls


class TestStaticMapEndpoint:
    def test_by_lat_lon(self, seed_data, client, offline_render):
        response = client.get("/v1/geo/map/static", {"lat": 46.5555, "lon": 8.1522})
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"
        assert len(response.content) > 1000

    def test_by_place_hut(self, seed_data, client, offline_render):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        response = client.get(
            "/v1/geo/map/static", {"place": hut.slug, "place_type": "hut"}
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"

    def test_rendered_once_then_from_storage(self, seed_data, client, offline_render):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        first = client.get(
            "/v1/geo/map/static", {"place": hut.slug, "place_type": "hut"}
        )
        assert first.status_code == 200
        tiles_after_first = offline_render["tiles"]
        assert tiles_after_first > 0
        assert (
            client.get(
                "/v1/geo/map/static", {"place": hut.slug, "place_type": "hut"}
            ).status_code
            == 200
        )
        assert offline_render["tiles"] == tiles_after_first

    def test_v_busts_cache(self, seed_data, client, offline_render):
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        base = {"place": hut.slug, "place_type": "hut"}
        assert client.get("/v1/geo/map/static", base).status_code == 200
        tiles_first = offline_render["tiles"]
        assert client.get("/v1/geo/map/static", {**base, "v": "2"}).status_code == 200
        assert offline_render["tiles"] > tiles_first

    def test_effects_and_params_validated(self, seed_data, client, offline_render):
        for effect in ("none", "blur_border", "spotlight", "vignette", "rounded"):
            response = client.get(
                "/v1/geo/map/static",
                {"lat": 46.5, "lon": 8.1, "effect": effect, "v": f"e-{effect}"},
            )
            assert response.status_code == 200
            assert len(response.content) > 1000
        assert (
            client.get(
                "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "effect": "nope"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "zoom": 3}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "basemap": "x"}
            ).status_code
            == 404
        )

    def test_marker_scale_param(self, seed_data, client, offline_render):
        response = client.get(
            "/v1/geo/map/static",
            {
                "lat": 46.5,
                "lon": 8.1,
                "marker": "symbol",
                "marker_scale": 2,
                "v": "scale",
            },
        )
        assert response.status_code == 200
        assert offline_render["marker"] == 0  # no place -> no symbol available

    def test_unknown_place_404(self, seed_data, client, offline_render):
        assert client.get("/v1/geo/map/static", {"place": "nope"}).status_code == 404

    def test_missing_coords_404(self, seed_data, client, offline_render):
        assert client.get("/v1/geo/map/static").status_code == 404


class TestMetaFallbacks:
    def test_hut_meta_no_photo_uses_static_map(
        self, seed_data, client, settings, offline_render
    ):
        from django.core.cache import cache

        from server.apps.huts.models import HutImageAssociation

        cache.clear()
        settings.FRONTEND_DOMAIN = "https://wodore.com"
        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        assert "/v1/geo/map/static" in data["image"]
        assert f"v={hut.modified:%Y%m%dT%H%M%S}" in data["image"]
        assert "place_type=hut" in data["image"]

    def test_place_meta_no_photo_uses_static_map(
        self, seed_data, client, settings, offline_render
    ):
        settings.FRONTEND_DOMAIN = "https://wodore.com"
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert "/v1/geo/map/static" in data["image"]
