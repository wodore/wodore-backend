"""Basemaps catalog tests — models, resolution, seed parity, endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from django.conf import settings
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
    missing_env_names,
    resolve_style,
    resolve_tokens,
    substitute_env,
)
from server.apps.basemaps.tile_assets import (
    ASSET_VERSIONS_CACHE_KEY,
    VERSIONED_TILE_SOURCES,
    asset_versions,
    inject_asset_versions,
    run_external_verifier,
    run_martin_watcher,
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


def _env_row(name: str = "WODORE_TEST_KEY", **overrides: Any) -> Any:
    """Create/update one env-registry row (signals drop the snapshot)."""
    from server.apps.envvars.models import EnvVar

    defaults: dict[str, Any] = {"value": "", "is_active": True, "env_fallback": True}
    defaults.update(overrides)
    return EnvVar.objects.update_or_create(name=name, defaults=defaults)[0]


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


@pytest.mark.django_db
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
        _env_row()  # registered, empty value → env fallback
        monkeypatch.setenv("WODORE_TEST_KEY", "abc123")
        assert (
            substitute_env("https://x/?key={{env:WODORE_TEST_KEY}}")
            == "https://x/?key=abc123"
        )

    def test_env_registry_strict_allowlist(self, monkeypatch):
        """Unregistered names never resolve — the process environment is
        never consulted for names outside the admin registry."""
        monkeypatch.setenv("WODORE_TEST_KEY", "from-env")
        assert (
            substitute_env("https://x/?key={{env:WODORE_TEST_KEY}}")
            == "https://x/?key={{env:WODORE_TEST_KEY}}"
        )

    def test_missing_env_names(self, monkeypatch):
        monkeypatch.delenv("WODORE_TEST_KEY", raising=False)
        monkeypatch.setattr(settings, "WODORE_TEST_KEY", "", raising=False)
        _env_row()
        document = {
            "sources": {"x": {"tiles": ["https://x/?key={{env:WODORE_TEST_KEY}}"]}}
        }
        assert missing_env_names(document) == {"WODORE_TEST_KEY"}

    def test_missing_env_names_resolvable_and_absent(self, monkeypatch):
        _env_row()
        monkeypatch.setenv("WODORE_TEST_KEY", "k")
        url = "https://x/?key={{env:WODORE_TEST_KEY}}"
        assert missing_env_names(url) == set()
        assert missing_env_names("https://x/tiles/{z}/{x}/{y}.png") == set()
        # An empty environment value is an accident, not intent — the
        # layer stays gated (pin an empty value to make it deliberate).
        monkeypatch.setenv("WODORE_TEST_KEY", "")
        assert missing_env_names(url) == {"WODORE_TEST_KEY"}

    def test_missing_env_names_pinned_empty(self, monkeypatch):
        _env_row(env_fallback=False)
        monkeypatch.setenv("WODORE_TEST_KEY", "from-env")
        url = "https://x/?key={{env:WODORE_TEST_KEY}}"
        assert missing_env_names(url) == set()
        assert substitute_env(url) == "https://x/?key="

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

    def test_medium_degrades_to_low(self):
        _raster_layer(slug="nearest", spec=MapLayer.Spec.high).save()
        _raster_layer(slug="nearest", spec=MapLayer.Spec.low).save()
        picked = MapLayer.pick_variant(
            MapLayer.objects.filter(slug="nearest"), "medium"
        )
        # Explicit chain (map-layers-api): medium → low → high — a
        # mid-tier device never upgrades to the heaviest variant.
        assert picked is not None and picked.spec == MapLayer.Spec.low

    def test_full_chains(self):
        for spec, expected in (
            ("low", MapLayer.Spec.medium),
            ("high", MapLayer.Spec.medium),
        ):
            _raster_layer(slug=f"chain-{spec}", spec=MapLayer.Spec.medium).save()
            picked = MapLayer.pick_variant(
                MapLayer.objects.filter(slug=f"chain-{spec}"), spec
            )
            assert picked is not None and picked.spec == expected

    def test_no_spec_serves_first(self):
        _raster_layer(slug="first", spec=MapLayer.Spec.low).save()
        picked = MapLayer.pick_variant(MapLayer.objects.filter(slug="first"), None)
        assert picked is not None and picked.spec == MapLayer.Spec.low

    def test_pick_accepts_prefetched_sequences(self):
        """The catalog resolves from prefetched lists, not querysets."""
        _raster_layer(slug="seq", spec=MapLayer.Spec.low).save()
        _raster_layer(slug="seq", spec=MapLayer.Spec.high).save()
        layers = list(MapLayer.objects.filter(slug="seq"))
        picked = MapLayer.pick_variant(layers, "medium")
        assert picked is not None and picked.spec == MapLayer.Spec.low


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
    def test_basemap_picker_visibility(self, django_db_setup):
        """Only product basemaps are pickable — internal variants and
        automatic fallbacks stay hidden but active (fallback chains,
        saved selections and spec variants keep resolving)."""
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        visible = list(
            MapLayer.objects.filter(
                role=MapLayer.Role.basemap, is_active=True, show=True
            )
            .order_by("order", "slug")
            .values_list("slug", flat=True)
            .distinct()
        )
        assert visible == [
            "wd-outdoor-base-mtk-hill",  # default outdoor
            "world-topo",
            "world-satellite-hybrid",
        ]
        hidden = {
            # plain non-hill pair retired (migration 0007); mtk-hill is
            # the visible product now, ofm-hill the hidden fallback
            "wd-outdoor-base-ofm-hill",
            "mtk-outdoor",  # upstream reference
            "ch-swisstopo-light",  # replaced by wd-outdoor-base-mtk
            "openfreemap-liberty",  # automatic keyless fallback
            "ch-swisstopo-full",  # owner call 2026-10-16: top-3 picker only
            "maptiler-hybrid",  # owner call 2026-10-16: top-3 picker only
        }
        rows = MapLayer.objects.filter(slug__in=hidden)
        assert rows.count() >= len(hidden)
        assert not rows.filter(show=True).exists()
        assert rows.filter(is_active=True).exists()  # hidden ≠ inactive

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
        mtk = MapLayer.objects.get(
            slug="wd-outdoor-base-mtk-hill", spec=MapLayer.Spec.high
        )
        fixture = json.loads((FIXTURES / "wd-outdoor-base-mtk-hill.json").read_text())
        assert mtk.style == fixture

    def test_resolved_style_no_root_relative_no_tokens(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)
        layer = MapLayer.objects.get(
            slug="wd-outdoor-base-mtk-hill", spec=MapLayer.Spec.high
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
        layer = MapLayer.objects.get(slug="huts")
        values = layer.authored_parameter_values()
        values["date"] = timezone.localdate().isoformat()
        resolved = resolve_style(layer.style, values)
        assert "{{date}}" not in json.dumps(resolved)
        # wd-bookings is the Martin `availability` vector source: the
        # {{date}} token substitutes inside the tile URL templates.
        tiles = resolved["sources"]["wd-bookings"]["tiles"]
        assert len(tiles) == 1
        assert f"date={values['date']}" in tiles[0]
        assert "/availability/{z}/{x}/{y}" in tiles[0]


# ── Endpoints ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLayersEndpoint:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_layers_envelope_and_resolution(self):
        self._seed()
        client = Client()
        response = client.get("/v1/map/layers", {"lang": "en"})
        assert response.status_code == 200
        payload = response.json()
        # Generic collection envelope (api-conventions)
        assert set(payload) == {"data", "count"}
        assert payload["count"] == len(payload["data"])
        entries = {layer["slug"]: layer for layer in payload["data"]}
        assert "huts" in entries
        assert "wd-outdoor-base-mtk-hill" in entries
        for entry in entries.values():
            # No variant arrays, no inline styles — one resolved layer
            assert "variants" not in entry
            assert entry["spec"] in ("low", "medium", "high")
            assert entry["style_url"]
            assert entry["modified"]  # ISO timestamp — client cache key
        mtk = entries["wd-outdoor-base-mtk-hill"]
        assert (
            mtk["style_url"] == "/v1/map/styles/wd-outdoor-base-mtk-hill.json?spec=high"
        )

    def test_role_and_show_filters(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/layers", {"lang": "en", "role": "overlay"}).json()
        assert payload["data"]
        assert all(layer["role"] == "overlay" for layer in payload["data"])
        # Default: hidden fallback basemaps stay resolvable (fallback
        # chains are resolved client-side)
        everything = client.get("/v1/map/layers", {"lang": "en"}).json()
        assert any(
            layer["slug"] == "wd-outdoor-base-ofm-hill" and layer["show"] is False
            for layer in everything["data"]
        )
        visible = client.get("/v1/map/layers", {"lang": "en", "show": "true"}).json()
        assert all(layer["show"] is True for layer in visible["data"])
        assert not any(
            layer["slug"] == "wd-outdoor-base-ofm" for layer in visible["data"]
        )

    def test_medium_degrades_cheaply_over_http(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/layers", {"lang": "en", "spec": "medium"}).json()
        entry = next(
            layer for layer in payload["data"] if layer["slug"] == "ch-swisstopo-light"
        )
        # Variants: high (vector) + low (raster) — medium must degrade
        # to the cheaper tier, never upgrade to high.
        assert entry["spec"] == "low"
        assert entry["style_url"].endswith("?spec=low")

    def test_sparse_fieldsets(self):
        self._seed()
        client = Client()
        payload = client.get(
            "/v1/map/layers",
            {"lang": "en", "fields[map_layers]": "slug,name,style_url"},
        ).json()
        assert payload["data"]
        for entry in payload["data"]:
            assert set(entry) == {"slug", "name", "style_url"}
        # Unknown field name → 400 with the valid names listed
        response = client.get(
            "/v1/map/layers", {"lang": "en", "fields[map_layers]": "slug,nope"}
        )
        assert response.status_code == 400

    def test_config_endpoint_removed(self):
        self._seed()
        response = Client().get("/v1/map/config", {"lang": "en"})
        assert response.status_code == 404

    def test_catalog_is_martin_parity_only(self):
        self._seed()
        payload = Client().get("/v1/map/catalog", {"lang": "en"}).json()
        assert set(payload) == {"styles"}
        for entry in payload["styles"].values():
            assert set(entry) == {"name", "path"}
            # Internal styles → style endpoint path; external styles →
            # their (env-resolved server-side) absolute URL
            assert entry["path"].startswith(("/v1/map/styles/", "http"))
        mtk = payload["styles"]["wd-outdoor-base-mtk-hill"]
        assert mtk["path"].startswith("/v1/map/styles/wd-outdoor-base-mtk-hill.json")

    def test_catalog_spec_resolution(self):
        """`?spec=` resolves into the path — exact tier when it exists,
        explicit chain otherwise (single variant serves its own spec)."""
        self._seed()
        payload = Client().get("/v1/map/catalog", {"lang": "en", "spec": "low"}).json()
        # ch-swisstopo-light HAS a low variant → path carries ?spec=low
        assert payload["styles"]["ch-swisstopo-light"]["path"].endswith("?spec=low")
        # wd-outdoor-base-mtk only exists at high → low falls through the
        # chain to the single variant, whose spec is reported
        assert payload["styles"]["wd-outdoor-base-mtk-hill"]["path"].endswith(
            "?spec=high"
        )

    def test_slots_endpoint(self):
        self._seed()
        payload = Client().get("/v1/map/slots", {"lang": "en"}).json()
        assert set(payload) == {"data", "count"}
        assert payload["count"] == len(payload["data"]) == 2
        assert {slot["slug"] for slot in payload["data"]} == {"background", "ways"}
        for slot in payload["data"]:
            assert set(slot) == {"slug", "label", "order"}
        # Slots ride their own endpoint, not the layers payload
        layers = Client().get("/v1/map/layers", {"lang": "en"}).json()
        assert "slots" not in layers

    def test_layer_detail(self):
        self._seed()
        client = Client()
        response = client.get("/v1/map/layers/huts", {"lang": "en"})
        assert response.status_code == 200
        entry = response.json()
        assert entry["slug"] == "huts"
        assert entry["legend"]["sections"]  # same shape as collection entries
        assert client.get("/v1/map/layers/nope", {"lang": "en"}).status_code == 404
        # Per-layer ETag: conditional revalidate answers 304
        etag = response.headers["ETag"]
        assert "must-revalidate" in response.headers["Cache-Control"]
        again = client.get(
            "/v1/map/layers/huts", {"lang": "en"}, HTTP_IF_NONE_MATCH=etag
        )
        assert again.status_code == 304

    def test_layers_etag_one_reload_freshness(self):
        """Edit → conditional GET answers non-304 — no time window."""
        from django.core.cache import cache

        self._seed()
        client = Client()
        first = client.get("/v1/map/layers", {"lang": "en"})
        etag = first.headers["ETag"]
        assert "must-revalidate" in first.headers["Cache-Control"]
        assert "stale-if-error" in first.headers["Cache-Control"]
        # Unchanged → 304 without rendering
        assert (
            client.get(
                "/v1/map/layers", {"lang": "en"}, HTTP_IF_NONE_MATCH=etag
            ).status_code
            == 304
        )
        # An edit becomes visible on the very next (conditional) reload.
        # NOTE: ``modified`` is bumped by a Postgres trigger using NOW(),
        # which is pinned to transaction start — inside one pytest test
        # every update shares a timestamp, so the observable version
        # input here is the row COUNT (create/delete); in production each
        # update is its own transaction and moves Max(modified) too.
        cache.clear()  # version memo + rendered body cache
        _raster_layer(slug="freshness-probe", spec=MapLayer.Spec.high).save()
        cache.clear()
        fresh = client.get("/v1/map/layers", {"lang": "en"}, HTTP_IF_NONE_MATCH=etag)
        assert fresh.status_code == 200
        assert fresh.headers["ETag"] != etag

    def test_layers_etag_varies_with_selection(self):
        self._seed()
        client = Client()
        plain = client.get("/v1/map/layers", {"lang": "en"})
        narrowed = client.get(
            "/v1/map/layers", {"lang": "en", "fields[map_layers]": "slug"}
        )
        spec = client.get("/v1/map/layers", {"lang": "en", "spec": "low"})
        etags = {
            plain.headers["ETag"],
            narrowed.headers["ETag"],
            spec.headers["ETag"],
        }
        assert len(etags) == 3  # different projections, different ETags


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
            "/v1/map/styles/wd-outdoor-base-mtk-hill.json", {"spec": "low"}
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


# ── Env-gated layers ─────────────────────────────────────────────


@pytest.mark.django_db
class TestEnvGatedLayers:
    """Layers with unresolvable ``{{env:…}}`` secrets are not servable.

    The catalog must never ship a style URL with a literal token —
    deployments without the key hide the layer entirely instead.
    """

    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    @staticmethod
    def _make_unavailable(monkeypatch):
        """Deterministically unset the MapTiler key (env ∪ settings)."""
        monkeypatch.delenv("WODORE_MAPTILER_API_KEY", raising=False)
        monkeypatch.setattr(settings, "WODORE_MAPTILER_API_KEY", "", raising=False)

    def test_hidden_from_layers_catalog_and_detail(self, monkeypatch):
        from django.core.cache import cache

        self._seed()
        self._make_unavailable(monkeypatch)
        cache.clear()  # version memo + rendered page cache
        client = Client()
        layers = client.get("/v1/map/layers", {"lang": "en"}).json()
        assert not any(l["slug"] == "maptiler-hybrid" for l in layers["data"])
        catalog = client.get("/v1/map/catalog", {"lang": "en"}).json()
        assert "maptiler-hybrid" not in catalog["styles"]
        detail = client.get("/v1/map/layers/maptiler-hybrid", {"lang": "en"})
        assert detail.status_code == 404

    def test_style_endpoint_names_the_unset_variable(self, monkeypatch):
        self._seed()
        self._make_unavailable(monkeypatch)
        response = Client().get("/v1/map/styles/maptiler-hybrid.json")
        assert response.status_code == 404
        payload = response.json()
        assert payload["code"] == "not_found"
        assert "WODORE_MAPTILER_API_KEY" in payload["detail"]

    def test_served_when_env_set(self, monkeypatch):
        from django.core.cache import cache

        self._seed()
        monkeypatch.setenv("WODORE_MAPTILER_API_KEY", "k1")
        cache.clear()
        client = Client()
        layers = client.get("/v1/map/layers", {"lang": "en"}).json()
        entry = next(l for l in layers["data"] if l["slug"] == "maptiler-hybrid")
        assert entry["style_url"].endswith("key=k1")
        catalog = client.get("/v1/map/catalog", {"lang": "en"}).json()
        assert catalog["styles"]["maptiler-hybrid"]["path"].endswith("key=k1")

    def test_inactive_registry_row_forbids_even_with_env(self, monkeypatch):
        """is_active=False is the operator kill switch — the layer is
        gated even when the process environment still has the key."""
        from django.core.cache import cache

        from server.apps.envvars.models import EnvVar

        self._seed()
        monkeypatch.setenv("WODORE_MAPTILER_API_KEY", "k1")
        # .update() fires no signals — clear the caches manually
        EnvVar.objects.filter(name="WODORE_MAPTILER_API_KEY").update(is_active=False)
        cache.clear()
        client = Client()
        layers = client.get("/v1/map/layers", {"lang": "en"}).json()
        assert not any(l["slug"] == "maptiler-hybrid" for l in layers["data"])
        assert client.get("/v1/map/styles/maptiler-hybrid.json").status_code == 404

    def test_admin_value_wins_over_env(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.envvars.models import EnvVar

        self._seed()
        monkeypatch.setenv("WODORE_MAPTILER_API_KEY", "from-env")
        EnvVar.objects.filter(name="WODORE_MAPTILER_API_KEY").update(value="from-admin")
        cache.clear()
        client = Client()
        layers = client.get("/v1/map/layers", {"lang": "en"}).json()
        entry = next(l for l in layers["data"] if l["slug"] == "maptiler-hybrid")
        assert entry["style_url"].endswith("key=from-admin")
        redirect = client.get("/v1/map/styles/maptiler-hybrid.json")
        assert redirect.status_code == 302
        assert redirect["Location"].endswith("key=from-admin")

    def test_pinned_empty_value_serves_empty_key(self, monkeypatch):
        """env_fallback=False + empty value = deliberately empty — the
        layer serves with the empty substitution (operator intent)."""
        from django.core.cache import cache

        from server.apps.envvars.models import EnvVar

        self._seed()
        monkeypatch.setenv("WODORE_MAPTILER_API_KEY", "ignored")
        EnvVar.objects.filter(name="WODORE_MAPTILER_API_KEY").update(env_fallback=False)
        cache.clear()
        redirect = Client().get("/v1/map/styles/maptiler-hybrid.json")
        assert redirect.status_code == 302
        assert redirect["Location"].endswith("key=")

    def test_catalog_etag_rotates_on_registry_edit(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.envvars.models import EnvVar

        self._seed()
        self._make_unavailable(monkeypatch)
        cache.clear()
        client = Client()
        first = client.get("/v1/map/layers", {"lang": "en"})
        # Signals fire (post_save) → availability memo + version cache reset
        EnvVar.objects.create(name="WODORE_ETAG_PROBE", value="x")
        second = client.get("/v1/map/layers", {"lang": "en"})
        assert second.headers["ETag"] != first.headers["ETag"]


# ── Legends ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLegends:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_catalog_serves_category_driven_legend(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/layers", {"lang": "en"}).json()
        huts = next(l for l in payload["data"] if l["slug"] == "huts")
        assert huts["legend"] is not None
        section = huts["legend"]["sections"][0]
        assert section["type"] == "symbol_dual"
        # Category-driven section embeds the minimal projection
        assert "category" in section

    def test_huts_layer_merged_with_availability(self):
        """huts-availability folded into huts: one overlay, two sources,
        one slug-level legend with two sections."""
        from server.apps.categories.models import Category

        # The availability category tree is curated (manually created on
        # staging; fresh DBs seed it later) — create the root so the
        # category links are exercised deterministically.
        Category.objects.get_or_create(
            slug="availability", parent=None, defaults={"name": "Availability"}
        )
        self._seed()
        assert not MapLayer.objects.filter(slug="huts-availability").exists()
        huts = MapLayer.objects.get(slug="huts")
        assert "wd-huts" in huts.style["sources"]
        assert "wd-bookings" in huts.style["sources"]
        layer_ids = {layer["id"] for layer in huts.style["layers"]}
        assert {"wd-huts", "wd-huts-selected", "wd-huts-occupation"} <= layer_ids
        assert "wd-huts-occupation-day3" in layer_ids
        # The date parameter drives the geojson source of the merged layer
        assert {link.parameter.slug for link in huts.layer_parameters.all()} == {
            "huts.icon_scale",
            "date",
        }
        # One legend, two sections: accommodation + availability (the
        # availability category resolves when the tree exists — staging
        # has it; the section itself is seeded regardless).
        assert huts.legend is not None
        section_types = [s.type for s in huts.legend.sections.all()]
        assert section_types == ["symbol_dual", "symbol_detailed"]
        categories = [
            section.category.slug
            for section in huts.legend.sections.all()
            if section.category
        ]
        assert categories == ["accommodation", "availability"]
        # Category links: accommodation filter+legend, availability legend
        uses = {(link.category.slug, link.use) for link in huts.layer_categories.all()}
        assert uses == {
            ("accommodation", "filter"),
            ("accommodation", "legend"),
            ("availability", "legend"),
        }

    def test_huts_sprites_match_martin_serving(self):
        """Icon names must match what Martin serves from the DB category
        sync (color/mono/primitive variants + SDF) — the old frontend
        simple/detailed prefixes exist in no served sprite."""
        self._seed()
        huts = MapLayer.objects.get(slug="huts").style
        sprite_urls = {s["id"]: s["url"] for s in huts["sprite"]}
        assert (
            sprite_urls["wd"] == "{TILE_SERVER_URL}/sprite/accommodation,availability"
        )
        assert sprite_urls["wd-sdf"] == "{TILE_SERVER_URL}/sdf_sprite/accommodation"
        body = json.dumps(huts)
        assert "simple/" not in body
        assert "detailed/" not in body
        assert "wd:primitive/accommodation.unknown" in body
        assert "wd-sdf:mono/accommodation.unknown" in body
        assert "wd:color/availability.unknown" in body

    def test_catalog_serves_static_legend_items(self):
        self._seed()
        client = Client()
        payload = client.get("/v1/map/layers", {"lang": "en"}).json()
        transport = next(l for l in payload["data"] if l["slug"] == "transport-stops")
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
        payload = client.get("/v1/map/layers", {"lang": "en"}).json()
        hiking = next(
            l
            for l in payload["data"]
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
        payload = client.get("/v1/map/layers", {"lang": "en"}).json()
        entry = next(l for l in payload["data"] if l["slug"] == "mtb")
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

    def test_per_spec_legend_divergence(self):
        """Each variant row serves its own legend (spec scenario)."""
        from django.core.cache import cache

        from server.apps.basemaps.models import MapLegend, MapLegendSection

        self._seed()
        low = _raster_layer(slug="diverge", spec=MapLayer.Spec.low)
        high = _raster_layer(slug="diverge", spec=MapLayer.Spec.high)
        legend_low = MapLegend.objects.create(title="Low legend")
        MapLegendSection.objects.create(
            legend=legend_low, order=0, title="Raster", type="line"
        )
        legend_high = MapLegend.objects.create(title="High legend")
        MapLegendSection.objects.create(
            legend=legend_high, order=0, title="Vector", type="point"
        )
        low.legend = legend_low
        low.save()
        high.legend = legend_high
        high.save()
        cache.clear()  # version memo — row counts changed
        client = Client()
        low_entry = client.get(
            "/v1/map/layers/diverge", {"lang": "en", "spec": "low"}
        ).json()
        high_entry = client.get(
            "/v1/map/layers/diverge", {"lang": "en", "spec": "high"}
        ).json()
        assert low_entry["legend"]["sections"][0]["title"] == "Raster"
        assert high_entry["legend"]["sections"][0]["title"] == "Vector"


# ── Style serving performance & version sync ───────────────────────────


@pytest.mark.django_db
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

        _env_row()  # registered, empty value → env fallback
        monkeypatch.setenv("WODORE_TEST_KEY", "v1")
        env = build_env({"WODORE_TEST_KEY"})
        assert env == {"WODORE_TEST_KEY": "v1"}

    def test_tree_substitution_single_pass(self, monkeypatch):
        from server.apps.basemaps.resolution import substitute_env_tree

        _env_row()
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
        payload = client.get("/v1/map/layers", {"lang": "en"}).json()
        entry = next(l for l in payload["data"] if l["slug"] == "huts")
        assert entry["modified"]  # ISO timestamp — client cache-sync key
        layer = MapLayer.objects.get(slug="huts", spec=MapLayer.Spec.medium)
        assert entry["modified"] == layer.modified.isoformat()

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


# ── Tile asset versioning ─────────────────────────────────────────────


@pytest.mark.django_db
class TestAssetVersionInjection:
    """Pure injection rules — no I/O, registry-shaped inputs."""

    def _versions(self, **overrides: Any) -> dict[str, Any]:
        versions: dict[str, Any] = {
            "sprites": "sprv",
            "fonts": "fntv",
            "tiles": {"huts": "hutv"},
            "external": {"https://icons.example.org/sprite": "extv"},
        }
        versions.update(overrides)
        return versions

    def test_sprite_glyphs_and_huts_tiles_get_versions(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        style = {
            "sprite": [
                {"id": "wd", "url": "https://tiles.example.org/sprite/accommodation"},
                {"id": "wd-sdf", "url": "https://tiles.example.org/sdf_sprite/acco"},
            ],
            "glyphs": "https://tiles.example.org/font/{fontstack}/{range}.pbf",
            "sources": {
                "wd-huts": {
                    "type": "vector",
                    "tiles": ["https://tiles.example.org/huts/{z}/{x}/{y}"],
                },
            },
        }
        out = inject_asset_versions(style, self._versions())
        assert out["sprite"][0]["url"].endswith("?v=sprv")
        assert out["sprite"][1]["url"].endswith("?v=sprv")
        assert out["glyphs"] == (
            "https://tiles.example.org/font/{fontstack}/{range}.pbf?v=fntv"
        )
        assert out["sources"]["wd-huts"]["tiles"][0] == (
            "https://tiles.example.org/huts/{z}/{x}/{y}?v=hutv"
        )

    def test_external_registry_urls_versioned(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        style = {
            "sprite": [{"id": "mtk", "url": "https://icons.example.org/sprite"}],
        }
        out = inject_asset_versions(style, self._versions())
        assert out["sprite"][0]["url"] == "https://icons.example.org/sprite?v=extv"

    def test_static_terrain_routes_and_tilejson_urls_versioned(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        style = {
            "sources": {
                "hillshade-server": {
                    "type": "raster",
                    "tiles": ["https://tiles.example.org/hillshade/{z}/{x}/{y}"],
                },
                "contours": {
                    "type": "vector",
                    "tiles": ["{TILE_SERVER_URL}/contours/{z}/{x}/{y}"],
                },
                "mtk": {
                    "type": "vector",
                    "url": "https://tiles.maptoolkit.org/mtk.json",
                },
            },
        }
        versions = {
            "sprites": None,
            "fonts": None,
            "tiles": {"hillshade": "hillv", "contours": "contv"},
            "external": {"https://tiles.maptoolkit.org/mtk.json": "mtkv"},
        }
        out = inject_asset_versions(style, versions)
        assert out["sources"]["hillshade-server"]["tiles"][0] == (
            "https://tiles.example.org/hillshade/{z}/{x}/{y}?v=hillv"
        )
        assert out["sources"]["contours"]["tiles"][0] == (
            "{TILE_SERVER_URL}/contours/{z}/{x}/{y}?v=contv"
        )
        assert out["sources"]["mtk"]["url"] == (
            "https://tiles.maptoolkit.org/mtk.json?v=mtkv"
        )
        from server.apps.basemaps.tile_assets import consumed_versions

        used = consumed_versions(style, versions)
        assert used["tiles"] == {"hillshade": "hillv", "contours": "contv"}
        assert used["external"] == {"https://tiles.maptoolkit.org/mtk.json": "mtkv"}

    def test_urls_with_query_or_param_tokens_untouched(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        style = {
            "sources": {
                "wd-bookings": {
                    "type": "vector",
                    "tiles": [
                        (
                            "https://tiles.example.org/availability/{z}/{x}/{y}"
                            "?date={{date}}&days=4"
                        )
                    ],
                },
                "raster-manual": {
                    "type": "raster",
                    "tiles": ["https://tiles.example.org/raster/{z}/{x}/{y}.webp?v=2"],
                },
            },
        }
        out = inject_asset_versions(style, self._versions())
        assert out["sources"]["wd-bookings"]["tiles"][0] == (
            "https://tiles.example.org/availability/{z}/{x}/{y}?date={{date}}&days=4"
        )
        assert out["sources"]["raster-manual"]["tiles"][0] == (
            "https://tiles.example.org/raster/{z}/{x}/{y}.webp?v=2"
        )

    def test_unregistered_sources_and_empty_registry_untouched(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        style = {
            "sprite": [
                {"id": "wd", "url": "https://tiles.example.org/sprite/accommodation"}
            ],
            "sources": {
                "geo": {
                    "type": "vector",
                    "tiles": ["https://tiles.example.org/geoplaces/{z}/{x}/{y}"],
                },
            },
        }
        empty = {"sprites": None, "fonts": None, "tiles": {}, "external": {}}
        assert inject_asset_versions(style, empty) == style
        out = inject_asset_versions(style, self._versions())
        # geoplaces is not registered → no version
        assert out["sources"]["geo"]["tiles"][0] == (
            "https://tiles.example.org/geoplaces/{z}/{x}/{y}"
        )


@pytest.mark.django_db
class TestAssetVersionServing:
    """Endpoint behavior: ETag body hash, cache-key digest rotation."""

    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def _publish(self, key: str, version: str):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.update_or_create(
            key=key,
            defaults={
                "version": version,
                "origin": TileAssetVersion.Origin.martin_sync,
            },
        )
        cache.delete(ASSET_VERSIONS_CACHE_KEY)

    def test_version_change_busts_etag_and_cache_without_layer_edit(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        first = client.get("/v1/map/styles/huts.json")
        assert "sprite/accommodation,availability?v=" not in first.content.decode()
        self._publish("sprites", "aaaaaaaa")
        second = client.get("/v1/map/styles/huts.json")
        assert second.headers["ETag"] != first.headers["ETag"]
        assert "sprite/accommodation,availability?v=aaaaaaaa" in second.content.decode()
        # Same body again from the render cache (key now embeds digest)
        third = client.get("/v1/map/styles/huts.json")
        assert third.headers["ETag"] == second.headers["ETag"]
        assert third.content == second.content

    def test_equal_length_version_change_busts_etag(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        self._publish("sprites", "aaaaaaaa")
        first = client.get("/v1/map/styles/huts.json")
        self._publish("sprites", "bbbbbbbb")  # same length, different content
        second = client.get("/v1/map/styles/huts.json")
        assert second.headers["ETag"] != first.headers["ETag"]
        assert "v=bbbbbbbb" in second.content.decode()

    def test_huts_tile_urls_versioned_from_computed_aggregate(self):
        from django.core.cache import cache

        self._seed()
        cache.clear()
        client = Client()
        body = client.get("/v1/map/styles/huts.json").json()
        huts = body["sources"]["wd-huts"]
        tiles = huts["tiles"][0]
        assert tiles.startswith("http")
        # The huts overlay opts into the MLT URL space (tile-router →
        # Martin serve-time conversion); the `?v=` asset version is
        # appended after the .mlt suffix.
        assert "/huts/{z}/{x}/{y}.mlt?v=" in tiles
        assert huts["encoding"] == "mlt"

    def test_category_edit_rotates_computed_huts_version(self):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion  # noqa: F401
        from server.apps.categories.models import Category

        cache.clear()
        versions = asset_versions(force=True)
        root = Category.objects.filter(parent=None).first()
        assert root is not None, "map_seed must provision root categories"
        root.name = {"en": "renamed"}  # type: ignore[assignment]
        root.save()
        import datetime as dt

        Category.objects.filter(pk=root.pk).update(
            modified=timezone.now() + dt.timedelta(seconds=5)
        )
        cache.delete(ASSET_VERSIONS_CACHE_KEY)
        rotated = asset_versions(force=True)
        assert rotated["tiles"]["huts"] != versions["tiles"]["huts"]

    def test_stored_terrain_rows_merge_into_tiles_versions(self):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.create(
            key="tiles:hillshade",
            origin=TileAssetVersion.Origin.martin_sync,
            version="hashv",
        )
        cache.delete(ASSET_VERSIONS_CACHE_KEY)
        versions = asset_versions(force=True)
        assert versions["tiles"].get("huts")  # computed still present
        assert versions["tiles"]["hillshade"] == "hashv"

    def test_deps_cover_every_table_joined_by_the_huts_view(self):
        """H1/H3 regression guard: the deps list must cover the view SQL."""
        import re

        from django.apps import apps

        from server.apps.huts.models.tiles_view import HutsForTilesView

        sql = HutsForTilesView.ViewMeta.query()[0]
        referenced = set(re.findall(r"(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", sql))
        dep_tables = {
            apps.get_model(label)._meta.db_table
            for label in VERSIONED_TILE_SOURCES["huts"]["deps"]
        }
        # No exclusions: a future view JOIN on an uncovered table (the
        # exact scenario this guard exists for) must fail this test.
        assert referenced == dep_tables, (
            f"view tables vs deps drift: missing={referenced - dep_tables} "
            f"extra={dep_tables - referenced}"
        )


class TestFetchSemantics:
    """_fetch against a REAL socket — urllib raises HTTPError for every
    non-2xx (including 304), which _fetch must normalize back into
    (status, body, headers); only network failures propagate."""

    def test_non2xx_returned_not_raised(self):
        import threading
        import urllib.error
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from server.apps.basemaps.tile_assets import _fetch

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/notmodified"):
                    self.send_response(304)
                    self.send_header("ETag", '"x"')
                    self.end_headers()
                elif self.path.startswith("/missing"):
                    self.send_response(404)
                    self.end_headers()
                else:
                    body = b"hello"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            status, body, headers = _fetch(f"{base}/notmodified", "n")
            assert (status, body, headers.get("ETag")) == (304, b"", '"x"')
            status, _body, _headers = _fetch(f"{base}/missing", "n")
            assert status == 404
            status, body, _headers = _fetch(f"{base}/ok", "n")
            assert (status, body) == (200, b"hello")
            with pytest.raises(urllib.error.URLError):
                _fetch("http://127.0.0.1:1/unreachable", "n")
        finally:
            server.shutdown()


@pytest.mark.django_db
class TestExternalVerifierHttpShapes:
    """Verifier behavior when the bare key 404s (the maptoolkit shape)."""

    def test_404_variant_skipped_and_json_png_publish(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.create(
            key="https://icons.example.org/sprite",
            origin=TileAssetVersion.Origin.external,
        )
        MapLayer.objects.create(
            slug="ext-layer",
            spec=MapLayer.Spec.medium,
            role=MapLayer.Role.overlay,
            name="Ext",
            style={
                "version": 8,
                "sprite": [{"id": "mtk", "url": "https://icons.example.org/sprite"}],
                "layers": [],
            },
        )
        cache.clear()

        def fetch(url, nonce, headers=None):
            if url.endswith(".json"):
                return 200, b"index", {"ETag": '"j"'}
            if url.endswith(".png"):
                return 200, b"pngbytes", {}
            return 404, b"", {}  # the bare extension-less key

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fetch)
        stats = run_external_verifier()
        assert _no_otm(stats["changed"]) == ["https://icons.example.org/sprite"]
        row = TileAssetVersion.objects.get(key="https://icons.example.org/sprite")
        assert row.version
        assert row.etag == '"j"'
        # Identical served bytes on the next run: unchanged, no rewrite
        stats2 = run_external_verifier()
        assert _no_otm(stats2["unchanged"]) == ["https://icons.example.org/sprite"]

    def test_mixed_304_and_changed_png_is_detected(self, monkeypatch):
        """M1 regression: a .json 304 must not mask a changed .png."""
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.create(
            key="https://icons.example.org/sprite",
            origin=TileAssetVersion.Origin.external,
            version="old",
            etag='"j"',
        )
        MapLayer.objects.create(
            slug="ext-layer",
            spec=MapLayer.Spec.medium,
            role=MapLayer.Role.overlay,
            name="Ext",
            style={
                "version": 8,
                "sprite": [{"id": "mtk", "url": "https://icons.example.org/sprite"}],
                "layers": [],
            },
        )
        cache.clear()

        def fetch(url, nonce, headers=None):
            if url.endswith(".json"):
                # Unchanged index: honors the stored validator.
                assert headers and headers.get("If-None-Match") == '"j"'
                return 304, b"", {}
            if url.endswith(".png"):
                return 200, b"recolored-png", {"ETag": '"p2"'}
            return 404, b"", {}

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fetch)
        stats = run_external_verifier()
        assert _no_otm(stats["changed"]) == ["https://icons.example.org/sprite"]


@pytest.mark.django_db
class TestPerStyleDigest:
    def test_huts_version_change_leaves_basemap_etags_alone(self):
        from django.core.cache import cache

        client = Client()
        self_layer = MapLayer.objects.filter(
            slug="world-topo", spec=MapLayer.Spec.medium
        ).first()
        if self_layer is None:
            from django.core.management import call_command

            call_command("map_seed", verbosity=0)
        cache.clear()
        basemap_before = client.get("/v1/map/styles/world-topo.json")
        huts_before = client.get("/v1/map/styles/huts.json")
        # Simulate a huts-data edit rotating the computed tile version
        from server.apps.basemaps import tile_assets

        original = tile_assets._computed_tile_versions

        def bumped():
            return {"huts": "rotated"}

        tile_assets._computed_tile_versions = bumped
        try:
            cache.delete(tile_assets.ASSET_VERSIONS_CACHE_KEY)
            basemap_after = client.get("/v1/map/styles/world-topo.json")
            huts_after = client.get("/v1/map/styles/huts.json")
        finally:
            tile_assets._computed_tile_versions = original
            cache.delete(tile_assets.ASSET_VERSIONS_CACHE_KEY)
        assert basemap_after.headers["ETag"] == basemap_before.headers["ETag"]
        assert huts_after.headers["ETag"] != huts_before.headers["ETag"]

    def test_consumed_versions_mirror_injection(self, settings):
        settings.MARTIN_TILE_URL = "https://tiles.example.org"
        from server.apps.basemaps.tile_assets import consumed_versions

        style = {
            "sprite": [
                {"id": "wd", "url": "{TILE_SERVER_URL}/sprite/accommodation"},
                {"id": "mtk", "url": "https://icons.example.org/sprite"},
            ],
            "glyphs": "{TILE_SERVER_URL}/font/{fontstack}/{range}.pbf",
            "sources": {
                "wd-huts": {
                    "type": "vector",
                    "tiles": ["{TILE_SERVER_URL}/huts/{z}/{x}/{y}"],
                },
            },
        }
        versions = {
            "sprites": "sprv",
            "fonts": "fntv",
            "tiles": {"huts": "hutv"},
            "external": {"https://icons.example.org/sprite": "extv"},
        }
        out = inject_asset_versions(
            {**style, "sprite": [dict(e) for e in style["sprite"]]}, versions
        )
        used = consumed_versions(style, versions)
        # Every injected ?v= corresponds to a consumed version, and every
        # consumed version appears on some URL in the injected tree.
        assert "?v=sprv" in out["sprite"][0]["url"]
        assert "?v=extv" in out["sprite"][1]["url"]
        assert out["glyphs"].endswith("?v=fntv")
        assert out["sources"]["wd-huts"]["tiles"][0].endswith("?v=hutv")
        assert used == {
            "sprites": "sprv",
            "fonts": "fntv",
            "tiles": {"huts": "hutv"},
            "external": {"https://icons.example.org/sprite": "extv"},
        }


@pytest.mark.django_db
class TestProbeShapes:
    """C1 regression: Martin has no handler for extension-less sprite
    base URLs — probes must target the served .json/.png variants."""

    def test_terrain_probes_absolutized_and_concrete(self):
        """Staging round 2: root-relative tile templates must become
        absolute probe URLs (raw '/hillshade/…' breaks urllib) — found
        live when tiles:hillshade/contours failed on staging."""
        from django.core.management import call_command

        from server.apps.basemaps.tile_assets import collect_martin_probes

        call_command("map_seed", verbosity=0)
        _sprites, _fonts, terrain = collect_martin_probes()
        assert "hillshade" in terrain and "contours" in terrain
        for route, urls in terrain.items():
            for url in urls:
                assert url.startswith(("http://", "https://")), (route, url)
                assert "{z}" not in url and "{x}" not in url and "{y}" not in url

    def test_sprite_probes_carry_json_png_suffixes(self):
        from django.core.management import call_command

        from server.apps.basemaps.tile_assets import collect_martin_probes

        call_command("map_seed", verbosity=0)
        sprite_urls, font_urls, _terrain = collect_martin_probes()
        assert sprite_urls, "seeded styles reference Martin sprites"
        for url in sprite_urls:
            assert url.endswith((".json", ".png")), url
            assert "/sprite/" in url or "/sdf_sprite/" in url
        bare = [
            u for u in sprite_urls if not (u.endswith(".json") or u.endswith(".png"))
        ]
        assert not bare
        # Fonts keep the template's .pbf (no double suffix)
        for url in font_urls:
            assert url.endswith("/0-255.pbf"), url


@pytest.mark.django_db
class TestDateRotation:
    """M2 regression: resolved styles with date params re-key at
    midnight; styles without them keep their ETag."""

    def test_date_change_rotates_huts_but_not_basemap(self, monkeypatch):
        from django.core.cache import cache
        from django.core.management import call_command
        from django.utils import timezone

        call_command("map_seed", verbosity=0)
        cache.clear()
        client = Client()
        huts_before = client.get("/v1/map/styles/huts.json")
        base_before = client.get("/v1/map/styles/world-topo.json")

        import datetime as dt

        tomorrow = timezone.localdate() + dt.timedelta(days=1)
        monkeypatch.setattr(timezone, "localdate", lambda: tomorrow)
        cache.clear()  # asset-version memo only; style keys embed the date

        huts_after = client.get("/v1/map/styles/huts.json")
        base_after = client.get("/v1/map/styles/world-topo.json")
        assert huts_after.headers["ETag"] != huts_before.headers["ETag"]
        assert base_after.headers["ETag"] == base_before.headers["ETag"]


@pytest.mark.django_db
class TestMartinWatcher:
    def _seed(self):
        from django.core.management import call_command

        call_command("map_seed", verbosity=0)

    def test_publishes_observed_hash_and_is_content_gated(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        self._seed()
        calls: list[str] = []

        def fake_fetch(url, nonce, headers=None):
            calls.append(url)
            assert nonce  # _fetch appends it as ?_wd_watch=…
            return 200, b"bytes-v1", {}

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fake_fetch)
        cache.clear()
        stats = run_martin_watcher()
        assert "sprites" in stats["published"]
        assert "fonts" in stats["published"]
        v1 = TileAssetVersion.objects.get(key="sprites").version
        # Unchanged served bytes → no republication
        stats2 = run_martin_watcher()
        assert "sprites" in stats2["kept"]
        assert "fonts" in stats2["kept"]
        assert TileAssetVersion.objects.get(key="sprites").version == v1
        # New served bytes → new version
        monkeypatch.setattr(
            "server.apps.basemaps.tile_assets._fetch",
            lambda url, nonce, headers=None: (200, b"bytes-v2", {}),
        )
        stats3 = run_martin_watcher()
        assert "sprites" in stats3["published"]
        assert "fonts" in stats3["published"]
        assert TileAssetVersion.objects.get(key="sprites").version != v1

    def test_font_probes_encode_spaces_and_skip_unknown_stacks(self, monkeypatch):
        """Staging round 1: font names contain spaces (raw URLs are
        invalid for urllib) and expression keywords scraped from
        data-driven text-font arrays 404 — those are skipped, real
        fonts still publish."""
        from django.core.cache import cache
        from django.core.management import call_command

        from server.apps.basemaps.models import TileAssetVersion
        from server.apps.basemaps.tile_assets import collect_martin_probes

        call_command("map_seed", verbosity=0)
        cache.clear()
        _sprites, fonts, _terrain = collect_martin_probes()
        assert fonts, "seeded styles reference Martin fonts"
        for url in fonts:
            assert " " not in url, url  # percent-encoded
        statuses: dict[str, int] = {}

        def fetch(url, nonce, headers=None):
            status = statuses.get(url, 200)
            return status, b"x" if status == 200 else b"", {}

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fetch)
        # One unknown (404) stack must not block the fonts group…
        unknown = next(u for u in fonts if u.endswith("/0-255.pbf"))
        statuses[unknown] = 404
        stats = run_martin_watcher()
        assert "sprites" in stats["published"]
        assert "fonts" in stats["published"]
        assert "tiles:hillshade" in stats["published"]  # seeded -hill style
        assert TileAssetVersion.objects.get(key="fonts").version
        assert TileAssetVersion.objects.get(key="tiles:hillshade").version
        # …but a 404 sprite is real breakage: sprites group fails.
        cache.clear()
        TileAssetVersion.objects.update(version="")
        statuses.clear()
        statuses[_sprites[0]] = 404
        stats2 = run_martin_watcher()
        assert stats2["failed"] == ["sprites"]
        assert "fonts" in stats2["published"]
        assert "tiles:hillshade" in stats2["published"]

    def test_probe_failure_keeps_stored_version(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        self._seed()
        TileAssetVersion.objects.update_or_create(
            key="sprites", defaults={"version": "stored"}
        )
        cache.clear()

        def failing_fetch(url, nonce, headers=None):
            raise OSError("martin down")

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", failing_fetch)
        stats = run_martin_watcher()
        assert "sprites" in stats["failed"]
        assert "fonts" in stats["failed"]
        assert TileAssetVersion.objects.get(key="sprites").version == "stored"


OTM_KEY = "https://tile.opentopomap.org/10/540/357.png"


def _no_otm(items: list) -> list:
    """Filter the always-verified OTM entry out of verifier stats lists."""
    return [i for i in items if i != OTM_KEY]


@pytest.mark.django_db
class TestExternalVerifier:
    def test_304_keeps_version_200_bumps(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.create(
            key="https://icons.example.org/sprite",
            origin=TileAssetVersion.Origin.external,
            version="old",
            etag='"abc"',
        )
        # Referenced by an active layer
        MapLayer.objects.create(
            slug="ext-layer",
            spec=MapLayer.Spec.medium,
            role=MapLayer.Role.overlay,
            name="Ext",
            style={
                "version": 8,
                "sprite": [{"id": "mtk", "url": "https://icons.example.org/sprite"}],
                "layers": [],
            },
        )
        cache.clear()

        def fetch_304(url, nonce, headers=None):
            assert headers and headers.get("If-None-Match") == '"abc"'
            return 304, b"", {}

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fetch_304)
        stats = run_external_verifier()
        assert _no_otm(stats["unchanged"]) == ["https://icons.example.org/sprite"]
        assert (
            TileAssetVersion.objects.get(key="https://icons.example.org/sprite").version
            == "old"
        )

        def fetch_200(url, nonce, headers=None):
            return 200, b"new-bytes", {"ETag": '"def"'}

        monkeypatch.setattr("server.apps.basemaps.tile_assets._fetch", fetch_200)
        stats2 = run_external_verifier()
        assert _no_otm(stats2["changed"]) == ["https://icons.example.org/sprite"]
        row = TileAssetVersion.objects.get(key="https://icons.example.org/sprite")
        assert row.version != "old"
        assert row.etag == '"def"'

    def test_unreferenced_entries_skipped(self, monkeypatch):
        from django.core.cache import cache

        from server.apps.basemaps.models import TileAssetVersion

        TileAssetVersion.objects.create(
            key="https://unreferenced.example.org/sprite",
            origin=TileAssetVersion.Origin.external,
            version="x",
        )
        cache.clear()
        stats = run_external_verifier()
        assert _no_otm(stats["changed"]) == []
        assert _no_otm(stats["unchanged"]) == []
        assert stats["failed"] == []
        # Everything seeded by migrations 0005/0006 is unreferenced in
        # this test's DB (no active layer references them here) plus the
        # test's own dead entry.
        seeded_unreferenced = sorted(
            [
                "https://unreferenced.example.org/sprite",
                "https://icons.maptoolkit.org/sprite",
                "https://icons.maptoolkit.org/nature~hsl_81_60_80",
                "https://icons.maptoolkit.org/water~hsl_182_65_80",
                "https://tiles.maptoolkit.org/mtk.json",
                "https://tiles.maptoolkit.org/contours.json",
                "https://tiles.maptoolkit.org/raster_bathymetry.json",
                "https://tiles.maptoolkit.org/terrainrgb.json",
                "https://tiles.maptoolkit.org/naturalearth.json",
                "https://tiles.maptoolkit.org/rocks.json",
            ]
        )
        assert _no_otm(stats["skipped"]) == seeded_unreferenced
        # Always-verified (OG renderer input): must never be skipped.
        assert OTM_KEY not in stats["skipped"]
        assert OTM_KEY in stats["changed"] + stats["unchanged"] + stats["failed"]


@pytest.mark.django_db
class TestOgMapMaintenance:
    """OG static cards: basemap content rotates the cache key; old
    cards are cleaned up daily."""

    def test_cache_key_includes_otm_version(self, db):
        from server.apps.api.ogmap import static_map_cache_key

        base = {
            "lat": "46.500000",
            "lon": "7.700000",
            "zoom": 15,
            "size": "1200x630",
            "basemap": "opentopomap@aaa",
            "marker": "symbol",
            "marker_scale": "1",
            "effect": "card",
            "attribution": "true",
            "symbol": "https://hub.example.org/media/symbols/x_hash1.svg",
        }
        rotated = {**base, "basemap": "opentopomap@bbb"}
        moved_symbol = {
            **base,
            "symbol": "https://hub.example.org/media/symbols/x_hash2.svg",
        }
        assert static_map_cache_key(rotated) != static_map_cache_key(base)
        assert static_map_cache_key(moved_symbol) != static_map_cache_key(base)

    def test_cleanup_deletes_only_old_cards(self):
        import os
        import time

        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from server.apps.basemaps.tile_assets import cleanup_og_maps

        default_storage.save("ogmaps/static-fresh.png", ContentFile(b"new"))
        old = "ogmaps/static-old.png"
        default_storage.save(old, ContentFile(b"old"))
        # backdate via os.utimes through the storage path
        stale = time.time() - 40 * 24 * 3600
        os.utime(default_storage.path(old), (stale, stale))
        stats = cleanup_og_maps()
        assert stats["deleted"] == 1
        assert default_storage.exists("ogmaps/static-fresh.png")
        assert not default_storage.exists(old)
        # Idempotent
        stats2 = cleanup_og_maps()
        assert stats2["deleted"] == 0
