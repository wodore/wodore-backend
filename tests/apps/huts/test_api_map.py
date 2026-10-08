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
    import io

    from PIL import Image

    calls = {"tiles": 0, "marker": 0}

    def _png_bytes(mode, size, color):
        buf = io.BytesIO()
        Image.new(mode, size, color).save(buf, format="PNG")
        return buf.getvalue()

    def fake_tile(zoom, x, y):
        calls["tiles"] += 1
        return Image.new("RGB", (ogmap.TILE_SIZE, ogmap.TILE_SIZE), (90, 120, 150))

    def fake_marker(symbol_url, size_px):
        calls["marker"] += 1
        return Image.new("RGBA", (size_px, size_px), (200, 60, 60, 255))

    async def fake_tile_retry_async(client, semaphore, zoom, x, y):
        calls["tiles"] += 1
        return _png_bytes("RGB", (ogmap.TILE_SIZE, ogmap.TILE_SIZE), (90, 120, 150))

    async def fake_marker_async(client, symbol_url, size_px):
        calls["marker"] += 1
        return _png_bytes("RGBA", (size_px, size_px), (200, 60, 60, 255))

    monkeypatch.setattr(ogmap, "_fetch_tile", fake_tile)
    monkeypatch.setattr(ogmap, "fetch_marker", fake_marker)
    # Async render path (the endpoint is async now): patch its fetchers too,
    # so tests never touch the network.
    monkeypatch.setattr(ogmap, "_fetch_tile_retry_async", fake_tile_retry_async)
    monkeypatch.setattr(ogmap, "fetch_marker_async", fake_marker_async)
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
        # The image service's static-map fallback feature, wrapped in
        # imagor like every og image (backend-served watermark
        # composited; the map URL is the encoded source).
        assert "map%2Fstatic" in data["image"]
        assert "size%3D1200x630" in data["image"]
        assert "effect%3Dspotlight" in data["image"]
        assert "marker_scale%3D0.56" in data["image"]
        assert "zoom%3D15" in data["image"]

    def test_place_meta_no_photo_uses_static_map(
        self, seed_data, client, settings, offline_render
    ):
        settings.FRONTEND_DOMAIN = "https://wodore.com"
        place = GeoPlace.objects.filter(
            is_active=True, is_public=True, name__gt=""
        ).first()
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}/meta").json()
        assert "map%2Fstatic" in data["image"]
        assert "effect%3Dspotlight" in data["image"]


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
        import email.message
        import urllib.error

        from PIL import Image

        from server.apps.api import ogmap

        calls = []

        def flaky(zoom, x, y):
            calls.append((x, y))
            if len(calls) == 1:
                headers = email.message.Message()
                headers["Retry-After"] = "0"
                raise urllib.error.HTTPError(
                    "url", 429, "Too Many Requests", headers, None
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


class TestLogoAssetEndpoint:
    """The watermark is served statically by the backend itself
    (/assets/logo/wodore_watermark.png) — the og/imagor pipeline no
    longer references the frontend-hosted copy."""

    def test_logo_is_served(self, client):
        response = client.get("/assets/logo/wodore_watermark.png")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"
        assert "max-age" in response.headers["Cache-Control"]
        assert response.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_unknown_asset_is_404(self, client):
        assert client.get("/assets/logo/other.png").status_code == 404
        assert client.get("/assets/logo/..%2Fsettings.py").status_code == 404

    def test_photo_og_url_uses_backend_logo(self, seed_data, client, monkeypatch):
        """og photo URLs embed the backend-served watermark (with the
        ?v= digest for imagor cache busting), not the frontend URL."""
        from urllib.parse import quote
        from uuid import uuid4

        from tests.apps.huts.test_api_meta import TestHutMetaOgSources

        from django.core.cache.backends.locmem import LocMemCache

        from server.apps.geometries import image_response_cache as irc

        cache = LocMemCache(f"test-{uuid4().hex}", {})
        monkeypatch.setattr(irc, "_cache", lambda: cache)

        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        from server.apps.huts.models import HutImageAssociation

        HutImageAssociation.objects.filter(hut=hut).delete()
        TestHutMetaOgSources._warm_gallery_cache(
            hut,
            TestHutMetaOgSources._gallery_response(
                hut, "https://media.camptocamp.org/c2corg-active/logo_check.jpg"
            ),
        )
        meta = client.get(f"/v1/huts/{hut.slug}/meta")
        assert meta.status_code == 200
        image = meta.json()["image"]
        assert (
            quote("static/logo/wodore_watermark.png", safe="") not in image
        )  # not the frontend-style path
        assert quote("/assets/logo/wodore_watermark.png?v=", safe="") in image
        assert "wodore.com/meta/" not in image


class TestSpotlightFalloff:
    """The spotlight effect is a smooth falloff — no inset, no frame:
    sharp colored center, darker desaturated (and gently blurred)
    outside. Regression for the rounded-inset 'border' look."""

    def _card(self, effect, offline_render):
        import io

        from PIL import Image

        return Image.open(
            io.BytesIO(ogmap.render_static_map(46.5, 8.0, zoom=15, effect=effect))
        ).convert("RGB")

    def test_outside_is_desaturated_center_keeps_color(self, offline_render):
        # Colored fake tiles: the ONLY saturation change comes from the
        # effect, not from map content.
        card = self._card("spotlight", offline_render)

        # Center keeps saturation (colored map); corners are grayscale-ish.
        def saturation(px):
            h, s, v = __import__("colorsys").rgb_to_hsv(*[c / 255 for c in px])
            return s

        center = saturation(card.getpixel((600, 315)))
        corner = saturation(card.getpixel((30, 30)))
        assert center > corner + 0.1, (center, corner)

    def test_no_hard_border_edge(self, offline_render):
        """Sample a horizontal strip: saturation must fall off gradually
        — no single step where saturation collapses (the old rounded
        inset produced a hard edge)."""
        import colorsys
        import itertools

        card = self._card("spotlight", offline_render)

        def sat(x):
            r, g, b = card.getpixel((x, 315))
            return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1]

        sats = [sat(x) for x in range(0, 1200, 24)]
        steps = [abs(a - b) for a, b in itertools.pairwise(sats)]
        assert max(steps) < 0.12, f"hard edge detected: max step {max(steps):.3f}"

    def test_render_version_busts_cache_key(self):
        key_a = ogmap.static_map_cache_key({"v": "x"})
        ogmap.RENDER_VERSION = ogmap.RENDER_VERSION + 1
        try:
            key_b = ogmap.static_map_cache_key({"v": "x"})
        finally:
            ogmap.RENDER_VERSION = ogmap.RENDER_VERSION - 1
        assert key_a != key_b
