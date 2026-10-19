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
    def test_martin_style_copies_match_fixtures(self):
        """The Martin-served copy of the default basemap must stay
        byte-identical to the backend fixture — nothing prevents drift
        between ``tile_server/styles/`` and ``fixtures/styles/``, and a
        stale copy would serve a different map than the API does."""
        tile_server = Path(__file__).resolve().parents[3] / "tile_server" / "styles"
        for slug in ("wd-outdoor-base-mtk-hill", "wd-outdoor-base-ofm-hill"):
            fixture = (FIXTURES / f"{slug}.json").read_bytes()
            copy = tile_server / f"{slug}.json"
            assert copy.exists(), f"missing Martin copy: {copy}"
            assert copy.read_bytes() == fixture, (
                f"{slug}.json: tile_server/styles copy differs from the "
                "fixture — regenerate it (see _work/261019_outdoor_map_fixes.md)"
            )

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
            "wd-outdoor-base-mtk",  # default outdoor
            "world-topo",
            "world-satellite-hybrid",
        ]
        hidden = {
            "wd-outdoor-base-ofm",  # hidden fallback (mtk chains to it)
            "wd-outdoor-base-mtk-hill",  # A/B variant
            "wd-outdoor-base-ofm-hill",  # A/B variant
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
        layer = MapLayer.objects.get(slug="huts")
        values = layer.authored_parameter_values()
        values["date"] = timezone.localdate().isoformat()
        resolved = resolve_style(layer.style, values)
        assert "{{date}}" not in json.dumps(resolved)
        assert str(resolved["sources"]["wd-bookings"]["data"]).endswith(".geojson")


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
        assert "wd-outdoor-base-mtk" in entries
        for entry in entries.values():
            # No variant arrays, no inline styles — one resolved layer
            assert "variants" not in entry
            assert entry["spec"] in ("low", "medium", "high")
            assert entry["style_url"]
            assert entry["modified"]  # ISO timestamp — client cache key
        mtk = entries["wd-outdoor-base-mtk"]
        assert mtk["style_url"] == "/v1/map/styles/wd-outdoor-base-mtk.json?spec=high"

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
            layer["slug"] == "wd-outdoor-base-ofm" and layer["show"] is False
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
        mtk = payload["styles"]["wd-outdoor-base-mtk"]
        assert mtk["path"].startswith("/v1/map/styles/wd-outdoor-base-mtk.json")

    def test_catalog_spec_resolution(self):
        """`?spec=` resolves into the path — exact tier when it exists,
        explicit chain otherwise (single variant serves its own spec)."""
        self._seed()
        payload = Client().get("/v1/map/catalog", {"lang": "en", "spec": "low"}).json()
        # ch-swisstopo-light HAS a low variant → path carries ?spec=low
        assert payload["styles"]["ch-swisstopo-light"]["path"].endswith("?spec=low")
        # wd-outdoor-base-mtk only exists at high → low falls through the
        # chain to the single variant, whose spec is reported
        assert payload["styles"]["wd-outdoor-base-mtk"]["path"].endswith("?spec=high")

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
