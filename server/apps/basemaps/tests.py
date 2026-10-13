"""Basemaps catalog tests — models, resolution, seed parity, endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from django.db import IntegrityError
from django.test import Client
from django.utils import timezone

from server.apps.basemaps import seed_lib
from server.apps.basemaps.models import (
    MapLayer,
    MapLayerParameter,
    MapParameter,
    MapSlot,
)
from server.apps.basemaps.resolution import (
    absolutize_urls,
    resolve_style,
    resolve_tokens,
    substitute_env,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "styles"


def _raster_layer(**overrides: Any) -> MapLayer:
    defaults: dict[str, Any] = {
        "slug": "test-overlay",
        "spec": MapLayer.Spec.medium,
        "role": MapLayer.Role.overlay,
        "name": "Test",
        "style": {
            "version": 8,
            "sources": {
                "wd-test": {
                    "type": "raster",
                    "tiles": ["https://example.com/{z}/{x}/{y}.png"],
                }
            },
            "layers": [{"id": "wd-test", "type": "raster", "source": "wd-test"}],
        },
    }
    defaults.update(overrides)
    return MapLayer(**defaults)


# ── Models ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestMapLayerConstraints:
    def test_style_xor_style_url(self):
        layer = _raster_layer(style_url="https://example.com/style.json")
        with pytest.raises(IntegrityError):
            layer.save()

    def test_unique_slug_spec(self):
        _raster_layer().save()
        with pytest.raises(IntegrityError):
            _raster_layer().save()

    def test_same_slug_different_spec_allowed(self):
        _raster_layer().save()
        second = _raster_layer(spec=MapLayer.Spec.high)
        second.save()
        assert MapLayer.objects.filter(slug="test-overlay").count() == 2

    def test_unknown_token_rejected(self):
        from django.core.exceptions import ValidationError

        layer = _raster_layer()
        layer.style["layers"][0]["paint"] = {"raster-opacity": "{{nope.opacity}}"}
        layer.save()  # DB constraints don't inspect tokens; clean() does
        with pytest.raises(ValidationError):
            layer.clean()


@pytest.mark.django_db
class TestParameterValidation:
    def test_opacity_curve_ascending_stops(self):
        from server.apps.basemaps.validation import (
            StyleValidationError,
            validate_opacity_curve,
        )

        with pytest.raises(StyleValidationError):
            validate_opacity_curve(
                ["interpolate", ["linear"], ["zoom"], 13, 0.8, 8, 0.2]
            )

    def test_opacity_curve_range(self):
        from server.apps.basemaps.validation import (
            StyleValidationError,
            validate_opacity_curve,
        )

        with pytest.raises(StyleValidationError):
            validate_opacity_curve(["interpolate", ["linear"], ["zoom"], 8, 1.5])

    def test_valid_curve_passes(self):
        from server.apps.basemaps.validation import validate_opacity_curve

        validate_opacity_curve(seed_lib.opacity_levels(0.1, 0.8, 0.3))


# ── Resolution ─────────────────────────────────────────────────────────


class TestResolution:
    def test_whole_node_token_becomes_subtree(self):
        curve = ["interpolate", ["linear"], ["zoom"], 8, 0, 16, 0.8]
        style = {"paint": {"raster-opacity": "{{x.opacity}}"}}
        resolved = resolve_tokens(style, {"x.opacity": curve})
        assert resolved["paint"]["raster-opacity"] == curve

    def test_inline_token_in_url(self):
        url = "{API_URL}/v1/huts/availability/{{date}}.geojson"
        resolved = resolve_tokens({"data": url}, {"date": "2026-10-12"})
        assert resolved["data"] == "{API_URL}/v1/huts/availability/2026-10-12.geojson"

    def test_none_values_never_substitute(self):
        resolved = resolve_tokens({"data": "{{date}}"}, {"date": None})
        assert resolved["data"] == "{{date}}"

    def test_env_substitution(self, monkeypatch):
        monkeypatch.setenv("WODORE_TEST_KEY", "abc123")
        assert (
            substitute_env("https://x/?key={{env:WODORE_TEST_KEY}}")
            == "https://x/?key=abc123"
        )

    def test_absolutize_root_relative_glyphs_and_sprite(self):
        style = {
            "glyphs": "/font/{fontstack}/{range}.pbf",
            "sprite": [{"id": "wd", "url": "/sprite/wd-maps"}],
        }
        out = absolutize_urls(style, "http://martin:8075")
        assert out["glyphs"] == "http://martin:8075/font/{fontstack}/{range}.pbf"
        assert out["sprite"][0]["url"] == "http://martin:8075/sprite/wd-maps"

    def test_absolutize_leaves_tokens(self):
        out = absolutize_urls({"data": "{{API_URL}}/x/{{date}}.geojson"}, "http://m")
        assert out["data"] == "{{API_URL}}/x/{{date}}.geojson"


@pytest.mark.django_db
class TestVariantSelection:
    def test_both_direction_fallback(self):
        _raster_layer(slug="only-high", spec=MapLayer.Spec.high).save()
        picked = MapLayer.pick_variant(MapLayer.objects.filter(slug="only-high"), "low")
        assert picked is not None and picked.spec == MapLayer.Spec.high

        _raster_layer(slug="only-low", spec=MapLayer.Spec.low).save()
        picked = MapLayer.pick_variant(MapLayer.objects.filter(slug="only-low"), "high")
        assert picked is not None and picked.spec == MapLayer.Spec.low

    def test_exact_match_wins(self):
        _raster_layer(slug="multi", spec=MapLayer.Spec.low).save()
        _raster_layer(slug="multi", spec=MapLayer.Spec.high).save()
        picked = MapLayer.pick_variant(MapLayer.objects.filter(slug="multi"), "high")
        assert picked is not None and picked.spec == MapLayer.Spec.high

    def test_nearest_tier(self):
        _raster_layer(slug="nearest", spec=MapLayer.Spec.high).save()
        _raster_layer(slug="nearest", spec=MapLayer.Spec.low).save()
        picked = MapLayer.pick_variant(
            MapLayer.objects.filter(slug="nearest"), "medium"
        )
        assert picked is not None and picked.spec in {
            MapLayer.Spec.low,
            MapLayer.Spec.high,
        }


@pytest.mark.django_db
class TestAuthoredOverrideOrder:
    def test_layer_override_wins_over_registry_default(self):
        param = MapParameter.objects.create(
            slug="x.opacity",
            kind=MapParameter.Kind.number,
            default=0.8,
        )
        layer = _raster_layer()
        layer.save()
        MapLayerParameter.objects.create(
            layer=layer, parameter=param, default_override=0.5
        )
        values = layer.authored_parameter_values()
        assert values["x.opacity"] == 0.5


# ── Seed & parity ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSeed:
    def test_seed_idempotent(self, django_db_setup):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        counts = (
            MapLayer.objects.count(),
            MapParameter.objects.count(),
            MapSlot.objects.count(),
        )
        call_command("map_seed", verbosity=0)
        assert counts == (
            MapLayer.objects.count(),
            MapParameter.objects.count(),
            MapSlot.objects.count(),
        )

    def test_mtk_style_parity_with_fixture(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        mtk = MapLayer.objects.get(slug="wd-outdoor-base-mtk", spec=MapLayer.Spec.high)
        fixture = json.loads((FIXTURES / "wd-outdoor-base-mtk.json").read_text())
        assert mtk.style == fixture

    def test_resolved_style_no_root_relative_no_tokens(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        layer = MapLayer.objects.get(
            slug="wd-outdoor-base-mtk", spec=MapLayer.Spec.high
        )
        resolved = resolve_style(layer.style, layer.authored_parameter_values())
        body = json.dumps(resolved)
        assert "{{" not in body.replace("{fontstack}", "").replace(
            "{range}", ""
        ).replace("{z}", "").replace("{x}", "").replace("{y}", "")
        # glyph/sprite URLs absolutized to the tile server
        assert str(resolved["glyphs"]).startswith("http")
        for sprite in resolved.get("sprite", []):
            assert sprite["url"].startswith("http") or sprite["url"].startswith(
                "https://icons"
            )

    def test_availability_runtime_date_token(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        layer = MapLayer.objects.get(slug="huts-availability")
        values = layer.authored_parameter_values()
        values["date"] = timezone.localdate().isoformat()
        resolved = resolve_style(layer.style, values)
        assert "{{date}}" not in json.dumps(resolved)
        assert str(resolved["sources"]["wd-bookings"]["data"]).endswith(".geojson")


# ── Endpoints ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCatalogEndpoint:
    def test_catalog_light_and_grouped(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        client = Client()
        response = client.get("/v1/map/catalog", {"lang": "en"})
        assert response.status_code == 200
        payload = response.json()
        slugs = {layer["slug"] for layer in payload["layers"]}
        assert "huts" in slugs
        assert "wd-outdoor-base-mtk" in slugs
        mtk = next(l for l in payload["layers"] if l["slug"] == "wd-outdoor-base-mtk")
        # Big style never inlined — the variant references the endpoint.
        for variant in mtk["variants"]:
            assert variant.get("inline_style") is None
            assert (
                variant["style_url"]
                == "/v1/map/styles/wd-outdoor-base-mtk.json?spec=high"
            )

    def test_role_filter(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        client = Client()
        response = client.get("/v1/map/catalog", {"lang": "en", "role": "overlay"})
        assert response.status_code == 200
        assert all(layer["role"] == "overlay" for layer in response.json()["layers"])


@pytest.mark.django_db
class TestStyleEndpoint:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_resolved_default_mode(self):
        self._seed()
        client = Client()
        response = client.get("/v1/map/styles/huts.json")
        assert response.status_code == 200
        assert response.headers["X-Map-Spec"] == "medium"
        style = response.json()
        assert style["version"] == 8
        body = json.dumps(style)
        assert "{{huts.icon_scale}}" not in body
        assert style["metadata"]["wd:served_spec"] == "medium"
        # placeholders resolved to the tile server
        assert not str(style["sprite"][0]["url"]).startswith("{TILE_SERVER_URL}")
        assert str(style["sprite"][0]["url"]).startswith("http")

    def test_tokenized_mode_keeps_tokens(self):
        self._seed()
        client = Client()
        response = client.get("/v1/map/styles/huts.json", {"mode": "tokenized"})
        assert response.status_code == 200
        assert "{{huts.icon_scale}}" in json.dumps(response.json())

    def test_spec_fallback_and_header(self):
        self._seed()
        client = Client()
        response = client.get(
            "/v1/map/styles/wd-outdoor-base-mtk.json", {"spec": "low"}
        )
        assert response.status_code == 200
        # only the high variant exists → served with reporting
        assert response.headers["X-Map-Spec"] == "high"

    def test_etag_304(self):
        self._seed()
        client = Client()
        first = client.get("/v1/map/styles/huts.json")
        etag = first.headers["ETag"]
        second = client.get("/v1/map/styles/huts.json", HTTP_IF_NONE_MATCH=etag)
        assert second.status_code == 304

    def test_external_style_redirects_with_env(self, monkeypatch):
        self._seed()
        monkeypatch.setenv("WODORE_MAPTILER_API_KEY", "k1")
        client = Client()
        response = client.get("/v1/map/styles/maptiler-hybrid.json")
        assert response.status_code == 302
        assert response["Location"].endswith("key=k1")

    def test_unknown_slug_404(self):
        self._seed()
        client = Client()
        response = client.get("/v1/map/styles/nope.json")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


# ── Legends ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLegends:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_catalog_serves_category_driven_legend(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/catalog", {"lang": "en"}).json()
        huts = next(l for l in payload["layers"] if l["slug"] == "huts")
        assert huts["legend"] is not None
        section = huts["legend"]["sections"][0]
        assert section["type"] == "symbol_dual"
        # Category-driven section embeds the minimal projection
        assert "category" in section

    def test_catalog_serves_static_legend_items(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/catalog", {"lang": "en"}).json()
        transport = next(l for l in payload["layers"] if l["slug"] == "transport-stops")
        items = transport["legend"]["sections"][0]["items"]
        assert {"label": "Train", "color": "#C60018"} in [
            {"label": i["label"], "color": i["color"]} for i in items
        ]

    def test_legend_external_links_m2m(self):
        self._seed()
        from server.apps.external_links.models import ExternalLink

        assert ExternalLink.objects.filter(
            url="https://www.schweizmobil.ch/de/wanderland.html"
        ).exists()
        client = Client()
        payload = client.get("/v1/map/catalog", {"lang": "en"}).json()
        hiking = next(
            l
            for l in payload["layers"]
            if l["slug"] == "ch.swisstopo.swisstlm3d-wanderwege"
        )
        urls = [link["url"] for link in hiking["legend"]["links"]]
        assert "https://www.schweizmobil.ch/de/wanderland.html" in urls

    def test_legend_token_passthrough(self):
        from server.apps.basemaps.models import (
            MapLegend,
            MapLegendItem,
            MapLegendSection,
        )

        self._seed()
        legend = MapLegend.objects.create(title="Variable legend")
        section = MapLegendSection.objects.create(
            legend=legend, order=99, title="Lines", type="line"
        )
        MapLegendItem.objects.create(
            section=section,
            order=0,
            label="Trail",
            color="{{trail_color}}",
            width="{{trail_width}}",
        )
        MapLayer.objects.filter(slug="mtb").update(legend=legend)

        from django.core.cache import cache

        cache.clear()  # catalog is page-cached — see fresh data
        client = Client()
        payload = client.get("/v1/map/catalog", {"lang": "en"}).json()
        entry = next(l for l in payload["layers"] if l["slug"] == "mtb")
        item = entry["legend"]["sections"][0]["items"][0]
        assert item["color"] == "{{trail_color}}"
        assert item["width"] == "{{trail_width}}"

    def test_variants_share_slug_level_legend(self):
        self._seed()
        huts = MapLayer.objects.get(slug="huts")
        assert huts.legend is not None
        MapLayer.objects.create(
            slug="huts",
            spec=MapLayer.Spec.high,
            role=huts.role,
            name=huts.name,
            style=huts.style,
            legend=huts.legend,
        )
        legend_ids = set(
            MapLayer.objects.filter(slug="huts").values_list("legend_id", flat=True)
        )
        assert None not in legend_ids and len(legend_ids) == 1


# ── Style serving performance & version sync ───────────────────────────


class TestEnvResolutionScoping:
    def test_collect_env_names(self):
        tree = {
            "url": "https://x/?key={{env:A_KEY}}",
            "layers": [{"id": "{{env:B_KEY}}"}],
        }
        from server.apps.basemaps.resolution import collect_env_names

        assert collect_env_names(tree) == {"A_KEY", "B_KEY"}

    def test_build_env_resolves_only_requested_names(self, monkeypatch):
        from server.apps.basemaps.resolution import build_env

        monkeypatch.setenv("WODORE_TEST_KEY", "v1")
        env = build_env({"WODORE_TEST_KEY"})
        assert env == {"WODORE_TEST_KEY": "v1"}

    def test_tree_substitution_single_pass(self, monkeypatch):
        from server.apps.basemaps.resolution import substitute_env_tree

        monkeypatch.setenv("WODORE_TEST_KEY", "k")
        tree = {
            "a": "{{env:WODORE_TEST_KEY}}",
            "b": ["{{env:WODORE_TEST_KEY}}", "plain"],
        }
        out = substitute_env_tree(tree)
        assert out == {"a": "k", "b": ["k", "plain"]}


@pytest.mark.django_db
class TestVersionFieldAndRenderCache:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_catalog_carries_version(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/catalog", {"lang": "en"}).json()
        entry = next(l for l in payload["layers"] if l["slug"] == "huts")
        assert entry["version"]  # ISO timestamp — client cache-sync key
        layer = MapLayer.objects.get(slug="huts", spec=MapLayer.Spec.medium)
        assert entry["version"] == layer.modified.isoformat()

    def test_style_metadata_carries_version(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        style = client.get("/v1/map/styles/huts.json").json()
        layer = MapLayer.objects.get(slug="huts", spec=MapLayer.Spec.medium)
        assert style["metadata"]["wd:version"] == layer.modified.isoformat()

    def test_render_cache_hits_and_stays_consistent(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        first = client.get("/v1/map/styles/huts.json")
        etag = first.headers["ETag"]
        # Cached render: identical body and ETag on the second request
        second = client.get("/v1/map/styles/huts.json")
        assert second.headers["ETag"] == etag
        assert second.content == first.content
        # And a 304 once the client sends the ETag back
        third = client.get("/v1/map/styles/huts.json", HTTP_IF_NONE_MATCH=etag)
        assert third.status_code == 304

    def test_style_edit_invalidates_cache(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        first = client.get("/v1/map/styles/huts.json")
        layer = MapLayer.objects.get(slug="huts", spec=MapLayer.Spec.medium)
        layer.style["layers"][0]["minzoom"] = 6
        layer.save()
        second = client.get("/v1/map/styles/huts.json")
        assert second.headers["ETag"] != first.headers["ETag"]


class TestSeedStyleSpecConformance:
    def test_huts_icon_size_keeps_zoom_top_level(self):
        """MapLibre style-spec: zoom only as top-level interpolate input."""
        huts = seed_lib.HUTS_STYLE
        symbol = next(l for l in huts["layers"] if l["id"] == "wd-huts")
        icon_size = symbol["layout"]["icon-size"]
        assert icon_size[0] == "interpolate"
        assert icon_size[2] == ["zoom"]
        assert icon_size[3] == 7  # first stop zoom
        # token folds into each stop value (valid expression position)
        assert icon_size[4] == ["*", 0.1, "{{huts.icon_scale}}"]

    def test_single_brace_api_url_substituted(self):
        out = absolutize_urls(
            {"data": "{API_URL}/v1/x.geojson"}, "http://m", api_url="https://api"
        )
        assert out["data"] == "https://api/v1/x.geojson"
