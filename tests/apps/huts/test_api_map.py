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

    calls = {"tiles": 0, "marker": 0}

    def fake_tile(zoom, x, y):
        calls["tiles"] += 1
        return Image.new("RGB", (ogmap.TILE_SIZE, ogmap.TILE_SIZE), (90, 120, 150))

    def fake_marker(symbol_url, size_px):
        calls["marker"] += 1
        return Image.new("RGBA", (size_px, size_px), (200, 60, 60, 255))

    monkeypatch.setattr(ogmap, "_fetch_tile", fake_tile)
    monkeypatch.setattr(ogmap, "fetch_marker", fake_marker)
    return calls


class TestStaticMapEndpoint:
    def test_by_lat_lon(self, seed_data, client, offline_render):
        response = client.get("/v1/geo/map/static", {"lat": 46.5555, "lon": 8.1522})
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/jpeg"
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
        assert response.headers["Content-Type"] == "image/jpeg"

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
        for effect in ("none", "blur_border", "spotlight", "vignette", "blurred_edges"):
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
    @pytest.fixture(autouse=True)
    def _isolated_cache(self, monkeypatch):
        from uuid import uuid4

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

    def test_hut_meta_no_photo_uses_static_map(
        self, seed_data, client, settings, offline_render
    ):
        from server.apps.huts.models import HutImageAssociation

        settings.FRONTEND_DOMAIN = "https://wodore.com"
        HutImageAssociation.objects.all().delete()
        hut = Hut.objects.filter(
            is_active=True, is_public=True, location__isnull=False
        ).first()
        assert hut is not None
        data = client.get(f"/v1/huts/{hut.slug}/meta").json()
        # The image service's static-map fallback feature, as-is: a
        # direct endpoint URL (no imagor wrapping — the render bakes the
        # watermark), og dimensions, spotlight, marker.
        assert "/v1/geo/map/static" in data["image"]
        assert "size=1200x630" in data["image"]
        assert "effect=spotlight" in data["image"]
        assert "marker_scale=0.8" in data["image"]
        assert "zoom=15" in data["image"]

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
        assert "effect=spotlight" in data["image"]


class TestSizeParameter:
    def test_size_renders(self, seed_data, client, offline_render):
        response = client.get(
            "/v1/geo/map/static",
            {"lat": 46.5, "lon": 8.1, "size": "600x315", "v": "s600"},
        )
        assert response.status_code == 200
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(response.content))
        assert img.size == (600, 315)

    def test_default_size(self, seed_data, client, offline_render):
        response = client.get(
            "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "v": "s-def"}
        )
        assert response.status_code == 200
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(response.content))
        assert img.size == (1200, 630)

    def test_attribution_param(self, seed_data, client, offline_render):
        with_attr = client.get(
            "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "v": "attr-on"}
        )
        without_attr = client.get(
            "/v1/geo/map/static",
            {"lat": 46.5, "lon": 8.1, "attribution": "false", "v": "attr-off"},
        )
        assert with_attr.status_code == without_attr.status_code == 200
        assert len(with_attr.content) > len(without_attr.content)  # text stripped

    def test_bad_size_404(self, seed_data, client, offline_render):
        assert (
            client.get(
                "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "size": "big"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/v1/geo/map/static", {"lat": 46.5, "lon": 8.1, "size": "50x50"}
            ).status_code
            == 404
        )


class TestTileThrottling:
    def test_429_retried_with_backoff(self, seed_data, monkeypatch):
        """A 429 on the first attempt is retried and succeeds."""
        import urllib.error

        from PIL import Image

        from server.apps.api import ogmap

        calls = []

        def flaky(zoom, x, y):
            calls.append((x, y))
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "url", 429, "Too Many Requests", {"Retry-After": "0"}, None
                )
            return Image.new("RGB", (256, 256))

        monkeypatch.setattr(ogmap, "_fetch_tile", flaky)
        tiles = ogmap._fetch_tiles(16, [(1, 1)])
        assert tiles[0].size == (256, 256)
        assert len(calls) == 2  # one 429, one success

    def test_parallel_fetch(self, seed_data, monkeypatch):
        from PIL import Image

        from server.apps.api import ogmap

        seen = []

        def recording(zoom, x, y):
            seen.append((x, y))
            return Image.new("RGB", (256, 256), (x % 255, y % 255, 100))

        monkeypatch.setattr(ogmap, "_fetch_tile", recording)
        tiles = ogmap._fetch_tiles(16, [(1, i) for i in range(8)])
        assert len(tiles) == 8
        assert len(seen) == 8


class TestMarkdownLanguageLinks:
    def test_hut_markdown_links_languages(self, seed_data, client):
        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        body = client.get(f"/v1/huts/{hut.slug}.md").content.decode()
        assert "Languages:" in body
        for label in ("Deutsch", "English", "Français", "Italiano"):
            assert label in body
        assert f"/hut/{hut.slug}.md?lang=en" in body

    def test_place_markdown_links_languages(self, seed_data, client):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        body = client.get(f"/v1/geo/places/{place.slug}.md").content.decode()
        assert "Languages:" in body
        assert f"/geo/places/{place.slug}.md?lang=fr" in body


class TestCategoriesIndexLang:
    def test_categories_index_lang_param(self, seed_data, client):
        default = client.get("/v1/categories/index.md")
        assert default.status_code == 200
        body = default.content.decode()
        assert body.startswith("# Wodore place categories")
        # the param is accepted (validated against the language choices)
        english = client.get("/v1/categories/index.md", {"lang": "en"})
        assert english.status_code == 200
        bad = client.get("/v1/categories/index.md", {"lang": "xx"})
        assert bad.status_code == 422


class TestBakedWatermark:
    """The Wodore watermark is baked into every card from the
    backend-bundled asset (no frontend dependency)."""

    def test_render_includes_the_logo(self, offline_render):
        import io

        from PIL import Image, ImageChops

        params = dict(lat=46.5, lon=8.0, zoom=15, effect="spotlight")
        with_logo = Image.open(io.BytesIO(ogmap.render_static_map(**params)))
        real = ogmap._watermark
        ogmap._watermark = lambda scale: None
        try:
            without = Image.open(io.BytesIO(ogmap.render_static_map(**params)))
        finally:
            ogmap._watermark = real
        diff = ImageChops.difference(with_logo.convert("RGB"), without.convert("RGB"))
        bbox = diff.getbbox()
        assert bbox is not None, "expected the watermark to change the card"
        # Owner-approved geometry: 270px at the 1200x630 reference, 33% of
        # the free width, 10px from the bottom. The PNG carries transparent
        # padding, so the visible edge sits slightly right of the anchor.
        left, top, right, bottom = bbox
        assert 300 <= left <= 345  # anchor at 0.33 * (1200 - 270) = 307
        assert 340 <= top <= 365  # anchor at 630 - 270 - 10 = 350
        assert right <= 590
        assert bottom <= 630

    def test_missing_asset_renders_without_logo(
        self, offline_render, monkeypatch, tmp_path
    ):
        import io

        from PIL import Image

        monkeypatch.setattr(ogmap, "_LOGO_PATH", tmp_path / "missing.png")
        monkeypatch.setattr(ogmap, "_logo_image", None)
        data = ogmap.render_static_map(46.5, lon=8.0, zoom=15)
        assert Image.open(io.BytesIO(data)).size == (1200, 630)

    def test_cache_key_busts_on_logo_change(self, monkeypatch, tmp_path):
        fake = tmp_path / "logo.png"
        fake.write_bytes(b"version-a")
        monkeypatch.setattr(ogmap, "_LOGO_PATH", fake)
        key_a = ogmap.static_map_cache_key({"v": "x"})
        fake.write_bytes(b"version-b")
        key_b = ogmap.static_map_cache_key({"v": "x"})
        assert key_a != key_b, "replacing the asset must re-render cached cards"
