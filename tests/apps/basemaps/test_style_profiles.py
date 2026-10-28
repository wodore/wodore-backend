"""Style profiles (full/subset): whitelist walker, resolution, tagging.

Covers the openspec change ``style-profiles-subset``:

* the pure-Python subset walker (acceptance: the served raster overlays,
  transport-stops-like circle styling; rejection: everything outside the
  v0.1 whitelist, path-precise),
* the model contract — ``(slug, spec, profile)`` uniqueness, rules
  ``version`` requirements, ``clean()`` gating, the ``config.clustering``
  shape check,
* ``pick_variant``'s 2D walk (tier respected before format richness;
  subset clients never receive full variants; omitted = today's
  profile-agnostic behavior),
* the one-time seed tagging + REAL seed gating (``update_or_create``
  bypasses ``clean()`` — the upsert calls the walker directly),
* the API surface — additive ``profile``/``version`` payload fields, the
  ``?profile=`` capability param, ``style_url`` byte-compat (no
  ``profile=`` param when the request carried none), distinct ETags per
  profile, and the ``validate_map_styles`` CI sweep.
"""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Generator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import Client, SimpleTestCase

from server.apps.basemaps import validation
from server.apps.basemaps.api import CATALOG_VERSION_CACHE_KEY, STYLE_BODIES_EPOCH_KEY
from server.apps.basemaps.management.commands.dump_map_styles import (
    Command as DumpCommand,
)
from server.apps.basemaps.management.commands.map_seed import (
    STYLE_SPEC_VERSION,
    Command,
)
from server.apps.basemaps.models import MapCoverage, MapLayer
from server.apps.basemaps.resolution import style_endpoint_url
from server.apps.basemaps.seed_lib import (
    TRANSPORT_STYLE_SUBSET,
    raster_style,
    swisstopo_overlay_style,
)
from server.apps.basemaps.validation import (
    SUBSET_REVISION,
    StyleValidationError,
    validate_clustering_config,
    validate_subset_style,
)

#: A raster overlay within the whitelist as-authored (the seeded shape).
SUBSET_RASTER: dict[str, Any] = {
    "version": 8,
    "name": "test-raster",
    "sources": {
        "wd-test": {
            "type": "raster",
            "tiles": ["https://tiles.example.org/test/{z}/{x}/{y}.png"],
            "tileSize": 256,
            "maxzoom": 16,
        }
    },
    "glyphs": "https://tiles.example.org/font/{fontstack}/{range}",
    "layers": [
        {
            "id": "wd-test",
            "type": "raster",
            "source": "wd-test",
            "minzoom": 8,
            "paint": {"raster-opacity": "{{test.opacity}}"},
        }
    ],
}

#: A full-only style — feature-state paint is explicitly outside v0.1.
FULL_CIRCLE: dict[str, Any] = {
    "version": 8,
    "name": "test-circle",
    "sources": {"pts": {"type": "geojson", "data": "https://example.org/pts.geojson"}},
    "layers": [
        {
            "id": "pts",
            "type": "circle",
            "source": "pts",
            "paint": {"circle-color": ["feature-state", "color"]},
        }
    ],
}

FILL_STYLE: dict[str, Any] = {
    "version": 8,
    "name": "fill",
    "sources": {"x": {"type": "geojson", "data": "https://example.org/x.geojson"}},
    "layers": [{"id": "x", "type": "fill", "source": "x"}],
}

CLUSTERING_CONFIG: dict[str, Any] = {
    "enabled": True,
    "source": "wd-huts",
    "groupByProperty": "type_standard_slug",
    "radius": 48,
    "maxZoom": 11,
    "bubble": {
        "colorProperty": "type_standard_color",
        "iconProperty": "type_standard_identifier",
        "countProperty": "point_count",
    },
}


def _circle_subset() -> dict[str, Any]:
    """transport-stops-shape: case/in/get color + zoom-interpolate."""
    return {
        "version": 8,
        "name": "stops",
        "sources": {
            "stops": {"type": "geojson", "data": "https://example.org/stops.geojson"}
        },
        "glyphs": "https://tiles.example.org/font/{fontstack}/{range}",
        "layers": [
            {
                "id": "stops",
                "type": "circle",
                "source": "stops",
                "paint": {
                    "circle-color": [
                        "case",
                        ["in", "train", ["get", "types"]],
                        "#C60018",
                        ["in", "bus", ["get", "types"]],
                        "#2d327d",
                        "#0079C7",
                    ],
                    "circle-radius": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        3,
                        16,
                        9,
                    ],
                },
            }
        ],
    }


def _occupation_subset() -> dict[str, Any]:
    """wd-huts-occupation-shape: circle-color as a match on a property."""
    return {
        "version": 8,
        "name": "occupation",
        "sources": {
            "wd-bookings": {
                "type": "vector",
                "tiles": ["https://tiles.example.org/availability/{z}/{x}/{y}.mlt"],
                "encoding": "mlt",
                "minzoom": 5,
                "maxzoom": 9,
            }
        },
        "layers": [
            {
                "id": "wd-huts-occupation",
                "type": "circle",
                "source": "wd-bookings",
                "source-layer": "availability",
                "paint": {
                    "circle-color": [
                        "match",
                        ["get", "d0_status"],
                        "available",
                        "#346751",
                        "full",
                        "#C60018",
                        "#888888",
                    ]
                },
            }
        ],
    }


# ── Walker (pure functions) ───────────────────────────────────────────


class SubsetWalkerAccepts(SimpleTestCase):
    def test_seeded_raster_overlay_style_passes(self) -> None:
        validate_subset_style(
            raster_style(
                "mtb",
                ["https://tile.waymarkedtrails.org/mtb/{z}/{x}/{y}.png"],
                opacity_token="mtb.opacity",
            )
        )

    def test_seeded_swisstopo_overlay_style_passes(self) -> None:
        validate_subset_style(
            swisstopo_overlay_style(
                "ch.swisstopo.swisstlm3d-wanderwege",
                "ch.swisstopo.swisstlm3d-wanderwege",
                opacity_token="hiking.opacity",
            )
        )

    def test_transport_stops_circle_shape_passes(self) -> None:
        validate_subset_style(_circle_subset())

    def test_occupation_match_shape_passes(self) -> None:
        validate_subset_style(_occupation_subset())

    def test_symbol_icon_simple_text_passes(self) -> None:
        style = deepcopy(SUBSET_RASTER)
        style["sprite"] = "https://tiles.example.org/sprite/wd"
        style["layers"] = [
            {
                "id": "sym",
                "type": "symbol",
                "source": "wd-test",
                "layout": {
                    "icon-image": "mono/accommodation.hut",
                    "icon-size": 1.2,
                    "icon-allow-overlap": True,
                    "text-field": ["get", "name"],
                    "text-font": ["Noto Sans Regular"],
                    "text-size": 12,
                },
                "paint": {"icon-opacity": ["case", ["has", "open"], 1.0, 0.5]},
            }
        ]
        validate_subset_style(style)

    def test_vector_encoding_mlt_passes(self) -> None:
        validate_subset_style(_occupation_subset())

    def test_transport_stops_subset_twin_passes_walker(self) -> None:
        """The seeded subset variant (promoteId/layout stripped, minzoom
        floor added) is walker-clean — the FULL document deliberately
        still is not (see the rejection test: it keeps promoteId)."""
        validate_subset_style(TRANSPORT_STYLE_SUBSET)

    def test_equality_operator_with_nested_get_passes(self) -> None:
        """``==`` is whitelisted but NOT identifier-shaped — it must be
        honored via the operator list (review fix #1), with nested
        expression operands still walked."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-opacity"] = [
            "case",
            ["==", ["get", "kind"], "station"],
            1,
            ["==", ["get", "kind"], "halt"],
            0.6,
            0.3,
        ]
        validate_subset_style(style)

    def test_match_with_label_set_passes(self) -> None:
        """``match`` labels may be literal scalar arrays — the operator-shape
        heuristic must not misread ``["residential", …]`` as an expression
        head (review fix #3)."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-color"] = [
            "match",
            ["get", "road_class"],
            ["residential", "service"],
            "#cccccc",
            "trunk",
            "#ff0000",
            "#888888",
        ]
        validate_subset_style(style)

    def test_in_with_literal_set_haystack_passes(self) -> None:
        """``in`` haystacks may be literal scalar arrays too (expression
        haystacks like transport-stops' stay expression-checked)."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-color"] = [
            "case",
            ["in", ["get", "kind"], ["bus", "tram"]],
            "#2d327d",
            "#0079C7",
        ]
        validate_subset_style(style)


class SubsetWalkerRejects(SimpleTestCase):
    def _reject(self, style: dict[str, Any], match: str) -> None:
        with pytest.raises(StyleValidationError, match=match):
            validate_subset_style(style)

    def test_fill_layer_rejected(self) -> None:
        self._reject(FILL_STYLE, r"layers\[0\]\.type")

    def test_feature_state_rejected(self) -> None:
        self._reject(FULL_CIRCLE, r"feature-state")

    def test_image_expression_rejected(self) -> None:
        style = deepcopy(SUBSET_RASTER)
        style["layers"][0]["type"] = "symbol"
        style["layers"][0]["layout"] = {"icon-image": ["image", "x"]}
        self._reject(style, r"operator 'image'")

    def test_non_zoom_interpolate_rejected(self) -> None:
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-radius"] = [
            "interpolate",
            ["linear"],
            ["get", "population"],
            0,
            2,
            100000,
            10,
        ]
        self._reject(style, r"input must be \['zoom'\]")

    def test_promote_id_source_key_rejected(self) -> None:
        style = deepcopy(_circle_subset())
        style["sources"]["stops"]["promoteId"] = "id"
        self._reject(style, r"sources\.stops\.promoteId")

    def test_vector_tilejson_url_rejected(self) -> None:
        style = deepcopy(_occupation_subset())
        style["sources"]["wd-bookings"] = {
            "type": "vector",
            "url": "https://tiles.example.org/huts.json",
        }
        self._reject(style, r"sources\.wd-bookings\.url")

    def test_wrong_encoding_value_rejected(self) -> None:
        style = deepcopy(_occupation_subset())
        style["sources"]["wd-bookings"]["encoding"] = "mvt"
        self._reject(style, r"encoding")

    def test_layout_visibility_rejected(self) -> None:
        style = deepcopy(_circle_subset())
        style["layers"][0]["layout"] = {"visibility": "visible"}
        self._reject(style, r"layout\.visibility")

    def test_top_level_terrain_rejected(self) -> None:
        style = deepcopy(SUBSET_RASTER)
        style["terrain"] = {"source": "wd-test", "exaggeration": 1}
        self._reject(style, r"terrain")

    def test_geojson_inline_data_rejected(self) -> None:
        style = deepcopy(_circle_subset())
        style["sources"]["stops"]["data"] = {"type": "FeatureCollection"}
        self._reject(style, r"data")

    def test_transport_stops_seed_style_is_not_yet_subset(self) -> None:
        """Whitelist-sufficiency evidence, not yet tagged: the served
        document carries promoteId + default layout.visibility — a subset
        variant is a trivial re-author (design D4/D6)."""
        from server.apps.basemaps.seed_lib import TRANSPORT_STYLE

        with pytest.raises(StyleValidationError):
            validate_subset_style(TRANSPORT_STYLE)


class ClusteringConfigTests(SimpleTestCase):
    def test_seed_schema_passes(self) -> None:
        validate_clustering_config(CLUSTERING_CONFIG)

    def test_literal_fallbacks_pass(self) -> None:
        validate_clustering_config(
            {"enabled": True, "source": "wd-huts", "bubble": {"color": "#346751"}}
        )

    def test_unknown_key_rejected(self) -> None:
        with pytest.raises(StyleValidationError, match="maxzoom"):
            validate_clustering_config({**CLUSTERING_CONFIG, "maxzoom": 11})

    def test_bad_types_rejected(self) -> None:
        with pytest.raises(StyleValidationError, match="enabled"):
            validate_clustering_config({**CLUSTERING_CONFIG, "enabled": "yes"})
        with pytest.raises(StyleValidationError, match="radius"):
            validate_clustering_config({**CLUSTERING_CONFIG, "radius": "big"})
        with pytest.raises(StyleValidationError, match="bubble.colorProperty"):
            validate_clustering_config(
                {**CLUSTERING_CONFIG, "bubble": {"colorProperty": 3}}
            )

    def test_non_object_rejected(self) -> None:
        with pytest.raises(StyleValidationError):
            validate_clustering_config(["enabled"])


# ── pick_variant (unsaved rows — no DB) ───────────────────────────────


def _row(spec: str, profile: str, order: int = 0) -> MapLayer:
    layer = MapLayer(slug="x", spec=spec, profile=profile, order=order)
    return layer


class PickVariantWalk(SimpleTestCase):
    def test_omitted_profile_prefers_full_at_tier(self) -> None:
        subset_medium = _row("medium", "subset")
        full_medium = _row("medium", "full")
        picked = MapLayer.pick_variant([subset_medium, full_medium], "medium")
        assert picked is full_medium

    def test_full_respects_tier_before_richness(self) -> None:
        subset_high = _row("high", "subset")
        full_medium = _row("medium", "full")
        picked = MapLayer.pick_variant([full_medium, subset_high], "high", "full")
        assert picked is subset_high

    def test_full_prefers_full_within_tier(self) -> None:
        subset_medium = _row("medium", "subset")
        full_medium = _row("medium", "full")
        picked = MapLayer.pick_variant([subset_medium, full_medium], "medium", "full")
        assert picked is full_medium

    def test_full_falls_back_through_chain(self) -> None:
        full_low = _row("low", "full")
        subset_medium = _row("medium", "subset")
        # high wanted: chain is (high, medium, low) — medium beats low.
        picked = MapLayer.pick_variant([full_low, subset_medium], "high", "full")
        assert picked is subset_medium

    def test_subset_never_receives_full(self) -> None:
        full_medium = _row("medium", "full")
        assert MapLayer.pick_variant([full_medium], "medium", "subset") is None

    def test_subset_walks_tiers(self) -> None:
        subset_low = _row("low", "subset")
        full_medium = _row("medium", "full")
        picked = MapLayer.pick_variant([full_medium, subset_low], "high", "subset")
        assert picked is subset_low

    def test_no_spec_returns_first_row(self) -> None:
        subset = _row("medium", "subset")
        full = _row("high", "full")
        assert MapLayer.pick_variant([full, subset], None) is full


# ── Model contract (DB) ───────────────────────────────────────────────


def _make(
    slug: str,
    spec: str = "medium",
    profile: str = "full",
    style: dict[str, Any] | None = None,
    version: str | None = None,
) -> MapLayer:
    return MapLayer.objects.create(
        slug=slug,
        spec=spec,
        profile=profile,
        style=style if style is not None else deepcopy(SUBSET_RASTER),
        version=version
        if version is not None
        else (SUBSET_REVISION if profile == "subset" else STYLE_SPEC_VERSION),
    )


def _unsaved(
    slug: str,
    spec: str = "medium",
    profile: str = "full",
    style: dict[str, Any] | None = None,
) -> MapLayer:
    """An UNSAVED instance for ``clean()``-path tests — the attribution
    requirement only fires on saved rows (``self.pk`` gate), so clean()
    tests avoid it by never touching the DB."""
    return MapLayer(
        slug=slug,
        spec=spec,
        profile=profile,
        style=style if style is not None else deepcopy(SUBSET_RASTER),
        version=SUBSET_REVISION if profile == "subset" else STYLE_SPEC_VERSION,
    )


@pytest.mark.django_db
class TestModelContract:
    def test_unique_slug_spec_profile(self) -> None:
        _make("dup", "medium", "full")
        with pytest.raises(IntegrityError):
            MapLayer.objects.create(
                slug="dup",
                spec="medium",
                profile="full",
                style=deepcopy(SUBSET_RASTER),
                version="1.0",
            )

    def test_same_slug_spec_two_profiles_allowed(self) -> None:
        _make("pair", "medium", "full", style=deepcopy(FULL_CIRCLE))
        _make("pair", "medium", "subset")
        assert MapLayer.objects.filter(slug="pair").count() == 2

    def test_invalid_profile_rejected(self) -> None:
        with pytest.raises(IntegrityError):
            MapLayer.objects.create(
                slug="bad",
                spec="medium",
                profile="leaflet",
                style=deepcopy(SUBSET_RASTER),
            )

    def test_clean_requires_version_for_inline(self) -> None:
        layer = _make("v", version="")
        layer.version = ""
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        assert "version" in excinfo.value.message_dict

    def test_clean_allows_empty_version_for_style_url(self) -> None:
        layer = MapLayer(
            slug="ext", spec="medium", style_url="https://example.org/s.json"
        )
        layer.clean()  # no version required

    def test_clean_validates_version_shape(self) -> None:
        layer = _make("vshape")
        layer.version = "not-a-version"
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        assert "version" in excinfo.value.message_dict

    def test_clean_runs_subset_walker(self) -> None:
        layer = _make("s", profile="subset", style=FILL_STYLE)
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        assert "style" in excinfo.value.message_dict

    def test_clean_accepts_valid_subset(self) -> None:
        style = deepcopy(SUBSET_RASTER)
        style["layers"][0]["paint"] = {"raster-opacity": 0.8}  # token-free
        layer = _unsaved("sok", profile="subset", style=style)
        layer.clean()

    def test_clean_validates_clustering_config(self) -> None:
        layer = _make("cl")
        layer.config = {"clustering": {**CLUSTERING_CONFIG, "bogus": 1}}
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        assert "config" in excinfo.value.message_dict


# ── Seed tagging + REAL gating ────────────────────────────────────────


@pytest.mark.django_db
class TestSeedTagging:
    def test_one_time_tagging(self) -> None:
        call_command("map_seed", verbosity=0)
        mtb = MapLayer.objects.get(slug="mtb", spec="medium")
        assert mtb.profile == "subset"
        assert mtb.version == SUBSET_REVISION
        world_topo = MapLayer.objects.get(slug="world-topo", spec="high")
        assert world_topo.profile == "subset"
        huts = MapLayer.objects.get(slug="huts", spec="medium")
        assert huts.profile == "full"
        assert huts.version == STYLE_SPEC_VERSION
        maptiler = MapLayer.objects.get(slug="maptiler-hybrid", spec="high")
        assert maptiler.profile == "full"
        assert maptiler.version == ""
        # Retagged in place — no orphan full twins beside the subset rows.
        assert not MapLayer.objects.filter(slug="mtb", profile="full").exists()

    def test_transport_stops_subset_variant_seeded(self) -> None:
        """The overlay serves BOTH profiles at the same tier: the authored
        full row (unchanged) plus the walker-clean subset twin for the
        Leaflet fallback."""
        call_command("map_seed", verbosity=0)
        full = MapLayer.objects.get(
            slug="transport-stops", spec="medium", profile="full"
        )
        assert full.version == STYLE_SPEC_VERSION
        subset = MapLayer.objects.get(
            slug="transport-stops", spec="medium", profile="subset"
        )
        assert subset.version == SUBSET_REVISION
        assert subset.style is not None
        assert "promoteId" not in subset.style["sources"]["transport-stops"]
        assert all("layout" not in layer for layer in subset.style["layers"])
        assert subset.style["layers"][0]["minzoom"] == 10

    def test_seed_idempotent_profiles(self) -> None:
        call_command("map_seed", verbosity=0)
        before = sorted(
            MapLayer.objects.values_list("slug", "spec", "profile", "version")
        )
        call_command("map_seed", verbosity=0)
        after = sorted(
            MapLayer.objects.values_list("slug", "spec", "profile", "version")
        )
        assert before == after

    def test_huts_config_carries_clustering(self) -> None:
        call_command("map_seed", verbosity=0)
        huts = MapLayer.objects.get(slug="huts", spec="medium")
        assert huts.config is not None
        assert huts.config["clustering"] == CLUSTERING_CONFIG
        assert "filters" in huts.config

    def test_seed_gate_rejects_non_subset_style(self) -> None:
        command = Command()
        parent = {
            "slug": "bad",
            "role": MapLayer.Role.overlay,
            "name": "Bad",
            "style": FILL_STYLE,
            "profile": MapLayer.Profile.subset,
            "version": SUBSET_REVISION,
        }
        with pytest.raises(StyleValidationError):
            command._seed_layer(parent, parent, {}, {}, {}, MapCoverage())

    def test_seed_gate_requires_version_for_inline(self) -> None:
        command = Command()
        parent = {
            "slug": "noversion",
            "role": MapLayer.Role.overlay,
            "name": "NoVersion",
            "style": deepcopy(SUBSET_RASTER),
            "profile": MapLayer.Profile.full,
            "version": "",
        }
        with pytest.raises(CommandError, match="rules version"):
            command._seed_layer(parent, parent, {}, {}, {}, MapCoverage())


@pytest.mark.django_db
class TestSweepCommand:
    def test_sweep_passes_after_seed(self) -> None:
        call_command("map_seed", verbosity=0)
        call_command("validate_map_styles")

    def test_sweep_fails_on_subset_drift(self) -> None:
        call_command("map_seed", verbosity=0)
        drifted = MapLayer.objects.filter(slug="mtb").update(style=FILL_STYLE)
        assert drifted == 1
        with pytest.raises(CommandError):
            call_command("validate_map_styles")

    def test_sweep_fails_on_missing_version(self) -> None:
        call_command("map_seed", verbosity=0)
        MapLayer.objects.filter(slug="cycling").update(version="")
        with pytest.raises(CommandError):
            call_command("validate_map_styles")


@pytest.mark.django_db
class TestDumpCommand:
    """dump_map_styles CI-input behavior: written files, walker-owned
    subset skips, and the _skipped.txt manifest for styl-ignored rows."""

    def test_dump_writes_full_skips_subset_and_ignored(self, tmp_path: Any) -> None:
        call_command(DumpCommand(), out=str(tmp_path))
        names = sorted(path.name for path in tmp_path.iterdir())
        # Authored full styles without an ignore list are dumped.
        assert "huts--medium--full.json" in names
        assert "transport-stops--medium--full.json" in names
        body = json.loads((tmp_path / "huts--medium--full.json").read_text())
        assert body["version"] == 8
        # Subset rows are walker-owned (never dumped) …
        assert "world-topo--high--subset.json" not in names
        assert "mtb--medium--subset.json" not in names
        # … and styl-ignored (["*"]) full rows are skipped + manifested —
        # the seed list is the single source of truth the CI job reads.
        assert "world-satellite-hybrid--high--full.json" not in names
        manifest = (tmp_path / "_skipped.txt").read_text().split()
        assert "world-satellite-hybrid" in manifest
        assert "ch-swisstopo-light" in manifest  # variant-level ["*"]
        assert "ch-swisstopo-full" in manifest
        assert "wd-outdoor-base-ofm-hill" in manifest
        assert "huts" not in manifest


# ── API surface ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestApiProfile:
    @pytest.fixture(autouse=True)
    def _clear_catalog_memos(self) -> Generator[None, None, None]:
        """Catalog memos and rendered bodies outlive the DB transaction —
        a prior test's cached body (keyed by an ETag folding the same
        memoized version + query string) can leak into this test's
        response and break exact-list assertions. Clear the memos around
        every test so each computes fresh keys (the same pattern as
        test_style_cache_epoch's ``_clean_epoch``)."""
        cache.delete(CATALOG_VERSION_CACHE_KEY)
        cache.delete(STYLE_BODIES_EPOCH_KEY)
        yield
        cache.delete(CATALOG_VERSION_CACHE_KEY)
        cache.delete(STYLE_BODIES_EPOCH_KEY)

    def _seed_variants(self) -> None:
        """Same-tier pair (medium full+subset) + a full-only slug — the
        omitted-profile resolution picks the first row by (role, order,
        slug, spec, profile): medium/full, full preferred within the
        tier."""
        _make("hybrid", "medium", "full", style=deepcopy(FULL_CIRCLE))
        _make("hybrid", "medium", "subset")
        _make("onlyfull", "medium", "full", style=deepcopy(FULL_CIRCLE))

    def _seed_tier_variants(self) -> None:
        """Cross-tier pair for the tier-before-richness walk."""
        _make("hybrid", "high", "subset")
        _make("hybrid", "medium", "full", style=deepcopy(FULL_CIRCLE))

    def test_seeded_subset_catalog_includes_transport_stops(self) -> None:
        """Owner report: 'public transport does not work' on the Leaflet
        fallback — the subset twin makes the overlay subset-servable at
        the same tier, and unprofiled clients keep the full row."""
        call_command("map_seed", verbosity=0)
        response = Client().get("/v1/map/layers?profile=subset")
        assert response.status_code == 200
        entries = {entry["slug"]: entry for entry in response.json()["data"]}
        assert "transport-stops" in entries
        entry = entries["transport-stops"]
        assert entry["profile"] == "subset"
        assert entry["version"] == SUBSET_REVISION
        assert "profile=subset" in entry["style_url"]
        # The style endpoint serves the subset document (no promoteId).
        style = Client().get("/v1/map/styles/transport-stops.json?profile=subset")
        assert style.status_code == 200
        assert "promoteId" not in style.json()["sources"]["transport-stops"]
        # Unprofiled requests keep today's behavior: the full row.
        unprofiled = Client().get("/v1/map/layers/transport-stops")
        assert unprofiled.json()["profile"] == "full"

    def _entry(self, client: Client, slug: str, query: str = "") -> dict[str, Any]:
        response = client.get(f"/v1/map/layers/{slug}{query}")
        assert response.status_code == 200, response.content
        return response.json()

    def test_omitted_profile_is_byte_compatible(self) -> None:
        self._seed_variants()
        entry = self._entry(Client(), "hybrid")
        assert entry["profile"] == "full"  # full preferred when both exist
        assert entry["version"] == STYLE_SPEC_VERSION
        assert "profile=" not in entry["style_url"]  # #331 byte-compat
        assert "spec=medium" in entry["style_url"]

    def test_profile_subset_resolves_subset_row(self) -> None:
        self._seed_variants()
        entry = self._entry(Client(), "hybrid", "?profile=subset")
        assert entry["profile"] == "subset"
        assert entry["version"] == SUBSET_REVISION
        assert "profile=subset" in entry["style_url"]

    def test_tier_respected_before_richness(self) -> None:
        self._seed_tier_variants()
        entry = self._entry(Client(), "hybrid", "?spec=high&profile=full")
        assert entry["spec"] == "high"
        assert entry["profile"] == "subset"  # subset@high beats full@medium

    def test_full_only_slug_absent_for_subset_clients(self) -> None:
        self._seed_variants()
        client = Client()
        listed = client.get("/v1/map/layers?profile=subset").json()["data"]
        assert [entry["slug"] for entry in listed] == ["hybrid"]
        assert client.get("/v1/map/layers/onlyfull?profile=subset").status_code == 404
        assert (
            client.get("/v1/map/styles/onlyfull.json?profile=subset").status_code == 404
        )

    def test_style_endpoint_serves_subset_row(self) -> None:
        self._seed_variants()
        response = Client().get("/v1/map/styles/hybrid.json?profile=subset")
        assert response.status_code == 200
        body = response.json()
        assert body["sources"]["wd-test"]["type"] == "raster"

    def test_etag_differs_per_profile(self) -> None:
        self._seed_variants()
        client = Client()
        unprofiled = client.get("/v1/map/layers").headers["ETag"]
        subset = client.get("/v1/map/layers?profile=subset").headers["ETag"]
        full = client.get("/v1/map/layers?profile=full").headers["ETag"]
        assert unprofiled != subset
        assert unprofiled != full
        assert subset != full


class StyleEndpointUrlTests(SimpleTestCase):
    def test_no_profile_param_when_omitted(self) -> None:
        assert style_endpoint_url("x", "medium") == "/v1/map/styles/x.json?spec=medium"

    def test_profile_param_appended_when_given(self) -> None:
        assert (
            style_endpoint_url("x", "medium", "subset")
            == "/v1/map/styles/x.json?spec=medium&profile=subset"
        )
        assert (
            style_endpoint_url("x", None, "subset")
            == "/v1/map/styles/x.json?profile=subset"
        )


# ── styl save-time integration (mocked subprocess — no binary needed) ─

#: Realistic styl diagnostics (first lines; ``-->``/``hint:`` dropped).
_STYL_E003 = (
    "error[E003] sources.roads: vector source missing required field "
    '"url" or "tiles"\n'
    "  --> style.json\n"
)
_STYL_W002 = (
    'warning[W002] layers[0].layout.visibility: layer "x" is permanently invisible\n'
)


def _fake_run(result: Any) -> Any:
    """A subprocess.run stand-in returning a canned completion."""

    def run(*args: Any, **kwargs: Any) -> Any:
        return result

    return run


def _explode(*args: Any, **kwargs: Any) -> Any:
    """Sentinel: subprocess.run must never be reached."""
    raise AssertionError("subprocess.run must not be called")


class TestStylRunner:
    """run_styl semantics: graceful absence, E/W split, ignore list
    (plain pytest class — the ``monkeypatch`` fixture needs pytest-style
    injection, not unittest-style)."""

    def test_absent_binary_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: None)
        assert validation.run_styl(deepcopy(SUBSET_RASTER)) is None

    def test_clean_exit_means_no_findings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(SimpleNamespace(returncode=0, stdout="", stderr="")),
        )
        assert validation.run_styl(deepcopy(SUBSET_RASTER)) == validation.StylResult(
            [], []
        )

    def test_e_code_violations_are_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(SimpleNamespace(returncode=1, stdout=_STYL_E003, stderr="")),
        )
        result = validation.run_styl(deepcopy(SUBSET_RASTER))
        assert result is not None
        assert result.errors == [
            (
                "E003 sources.roads: vector source missing required field "
                '"url" or "tiles"'
            )
        ]
        assert result.warnings == []

    def test_ignored_codes_are_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(
                SimpleNamespace(returncode=1, stdout=_STYL_E003 + _STYL_W002, stderr="")
            ),
        )
        result = validation.run_styl(
            deepcopy(SUBSET_RASTER), ignored_rules=("E003", "W002")
        )
        assert result == validation.StylResult([], [])

    def test_star_skips_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(validation.subprocess, "run", _explode)
        assert (
            validation.run_styl(deepcopy(SUBSET_RASTER), ignored_rules=("*",)) is None
        )

    def test_timeout_degrades_to_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")

        def run(command: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=command, timeout=10)

        monkeypatch.setattr(validation.subprocess, "run", run)
        result = validation.run_styl(deepcopy(SUBSET_RASTER))
        assert result is not None
        assert result.errors == []
        assert any("timed out" in warning for warning in result.warnings)

    def test_tool_error_degrades_to_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(SimpleNamespace(returncode=2, stdout="", stderr="boom")),
        )
        result = validation.run_styl(deepcopy(SUBSET_RASTER))
        assert result is not None
        assert result.errors == []
        assert any("tool error" in warning for warning in result.warnings)

    def test_unparsable_output_degrades_to_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(SimpleNamespace(returncode=1, stdout="total garbage", stderr="")),
        )
        result = validation.run_styl(deepcopy(SUBSET_RASTER))
        assert result is not None
        assert result.errors == []
        assert any("unparsable" in warning for warning in result.warnings)


@pytest.mark.django_db
class TestStylSaveGate:
    """MapLayer.clean() and the seed upsert block on non-ignored E-codes."""

    def _with_styl(
        self, monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 1
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(
            validation.subprocess,
            "run",
            _fake_run(SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")),
        )

    def test_e_code_blocks_save(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_styl(monkeypatch, _STYL_E003)
        layer = _unsaved("stye", profile="full", style=deepcopy(FULL_CIRCLE))
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        message = str(excinfo.value.message_dict["style"])
        assert "styl:" in message
        assert "E003" in message

    def test_ignore_list_bypasses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_styl(monkeypatch, _STYL_E003)
        layer = _unsaved("styi", profile="full", style=deepcopy(FULL_CIRCLE))
        layer.styl_ignored_rules = ["E003"]
        layer.clean()

    def test_star_skips_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(validation.subprocess, "run", _explode)
        layer = _unsaved("stys", profile="full", style=deepcopy(FULL_CIRCLE))
        layer.styl_ignored_rules = ["*"]
        layer.clean()

    def test_w_codes_surface_next_to_blocking_e(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_styl(monkeypatch, _STYL_E003 + _STYL_W002)
        layer = _unsaved("styw", profile="full", style=deepcopy(FULL_CIRCLE))
        with pytest.raises(ValidationError) as excinfo:
            layer.clean()
        message = str(excinfo.value.message_dict["style"])
        assert "E003" in message
        assert "warnings:" in message
        assert "W002" in message

    def test_w_codes_alone_never_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_styl(monkeypatch, _STYL_W002)
        layer = _unsaved("styw2", profile="full", style=deepcopy(FULL_CIRCLE))
        layer.clean()

    def test_absent_binary_skips_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: None)
        monkeypatch.setattr(validation.subprocess, "run", _explode)
        layer = _unsaved("styn", profile="full", style=deepcopy(FULL_CIRCLE))
        layer.clean()

    def test_seed_gate_blocks_on_styl_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_styl(monkeypatch, _STYL_E003)
        command = Command()
        parent = {
            "slug": "styseed",
            "role": MapLayer.Role.overlay,
            "name": "StySeed",
            "style": deepcopy(FULL_CIRCLE),
        }
        with pytest.raises(CommandError, match="E003"):
            command._seed_layer(parent, parent, {}, {}, {}, MapCoverage())

    def test_seed_star_ignores_styl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validation, "_styl_binary", lambda: "/usr/bin/styl")
        monkeypatch.setattr(validation.subprocess, "run", _explode)
        command = Command()
        parent = {
            "slug": "styseed2",
            "role": MapLayer.Role.overlay,
            "name": "StySeed2",
            "style": deepcopy(SUBSET_RASTER),
            "profile": MapLayer.Profile.subset,
            "version": SUBSET_REVISION,
            "styl_ignored_rules": ["*"],
        }
        created, _ = command._seed_layer(parent, parent, {}, {}, {}, MapCoverage())
        assert created == 1

    def test_sweep_fails_on_styl_e_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_styl(monkeypatch, _STYL_E003)
        _make("stysweep", profile="full", style=deepcopy(FULL_CIRCLE))
        stderr = io.StringIO()
        with pytest.raises(CommandError, match="style violation"):
            call_command("validate_map_styles", stderr=stderr)
        assert "E003" in stderr.getvalue()  # details name the row and code

    def test_sweep_passes_on_w_codes_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_styl(monkeypatch, _STYL_W002)
        _make("stysweep2", profile="full", style=deepcopy(FULL_CIRCLE))
        call_command("validate_map_styles")  # W-codes never block
