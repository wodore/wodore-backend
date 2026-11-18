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
    ACCOMMODATIONS_STYLE,
    ACCOMMODATIONS_STYLE_SUBSET,
    HUTS_STYLE,
    HUTS_STYLE_SUBSET,
    TRANSPORT_STYLE,
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
    "maxZoom": 10,
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

    def test_transport_stops_style_passes_walker(self) -> None:
        """The subset twin is walker-clean by construction; the FULL
        document is not (feature-state, halo paints — by design, the
        accommodations pattern)."""
        validate_subset_style(TRANSPORT_STYLE_SUBSET)

    def test_huts_subset_twin_passes_walker(self) -> None:
        """The huts twin (availability disc + trimmed symbol) is
        walker-clean; the FULL document still fails — day-strip
        concat/image/to-string, the feature-state selection circle and
        the text-field ``>`` comparison are all outside v0.1."""
        validate_subset_style(HUTS_STYLE_SUBSET)
        with pytest.raises(StyleValidationError):
            validate_subset_style(HUTS_STYLE)

    def test_accommodations_subset_twin_passes_walker(self) -> None:
        """The geoplaces accommodations twin (cluster bubbles + tinted
        fallback icon) is walker-clean; the FULL document fails on the
        icon ladder (concat/image/coalesce), the count labels
        (to-string) and the feature-state selection circle."""
        validate_subset_style(ACCOMMODATIONS_STYLE_SUBSET)
        with pytest.raises(StyleValidationError):
            validate_subset_style(ACCOMMODATIONS_STYLE)

    def test_accommodations_source_mlt_pairing(self) -> None:
        """The accommodations tiles template carries a query string
        AFTER the ``.mlt`` suffix (cluster/filter params) — the pairing
        contract (.mlt path ⇒ ``encoding: mlt``) must hold, and the
        function-source URL params must survive resolution."""
        source = ACCOMMODATIONS_STYLE["sources"]["wd-accommodations"]
        template = source["tiles"][0]
        assert template.split("?", 1)[0].endswith(".mlt")
        assert source["encoding"] == "mlt"
        assert "category_tree=accommodation" in template
        # popup props ride the fields list (tile-function opt-in,
        # migration geometries.0077): elevation + category_identifier
        assert "category_identifier" in template
        assert "elevation" in template

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

    def test_clustered_transport_subset_shape_passes(self) -> None:
        """Clustering bits the subset whitelist admits for the fallback:
        geojson ``cluster*`` source keys, the layer ``filter`` key
        (including ``!``), ``>`` comparisons and interpolate on a
        ``['get', '<property>']`` input (cluster bubble sizing)."""
        style = deepcopy(_circle_subset())
        style["sources"]["stops"] = {
            "type": "geojson",
            "data": "https://example.org/stops.geojson",
            "cluster": True,
            "clusterMaxZoom": 6,
            "clusterRadius": 20,
            "clusterProperties": {
                "train_count": ["+", ["case", ["in", "train", ["get", "types"]], 1, 0]],
            },
        }
        style["layers"][0]["filter"] = ["!", ["has", "point_count"]]
        style["layers"][0]["paint"]["circle-color"] = [
            "case",
            [">", ["get", "train_count"], 0],
            "#C60018",
            "#0079C7",
        ]
        style["layers"][0]["paint"]["circle-radius"] = [
            "interpolate",
            ["linear"],
            ["get", "point_count"],
            2,
            5,
            100,
            10,
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
        """Interpolate on an arbitrary EXPRESSION input stays out —
        only ['zoom'] and ['get', '<property>'] are whitelisted."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-radius"] = [
            "interpolate",
            ["linear"],
            [">", ["get", "population"], 0],
            0,
            2,
            100000,
            10,
        ]
        self._reject(style, r"interpolate input must be \['zoom'\] or \['get'")

    def test_interpolate_nested_expression_input_rejected(self) -> None:
        """The widened interpolate input admits ONLY ['zoom'] and
        ['get', '<literal property>'] — a nested expression input stays
        out."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["paint"]["circle-radius"] = [
            "interpolate",
            ["linear"],
            ["get", ["get", "prop"]],
            0,
            2,
            10,
            10,
        ]
        self._reject(style, r"interpolate input must be")

    def test_filter_with_non_whitelisted_operator_rejected(self) -> None:
        """``!=`` is not whitelisted — the filter array is not
        expression-headed, so the walker reads it as a literal array and
        rejects the nested expression entry."""
        style = deepcopy(_circle_subset())
        style["layers"][0]["filter"] = ["!=", ["get", "kind"], "station"]
        self._reject(style, r"literal array entries must be scalars")

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


class TransportVectorContractTests(SimpleTestCase):
    """transport-stops on Transitland vector tiles (Martin passthrough,
    MLT URL space): the style contract beyond the generic walker.

    * FULL row + subset twin (accommodations pattern): the full
      document carries the hut-style look — SDF sprite icons tinted
      by the stop's mode color, white halo ladder, hover halo recolor,
      selected plate + ring (feature-state is subset-forbidden); the
      twin is the previous single subset document (plain sprite,
      no halo/hover) for Leaflet fallback sessions.
    * one vector source — the Martin proxy of the Transitland stops
      tileset — on the explicit ``.mlt`` URL space with the MapLibre
      decoder marker (pairing contract: a ``.mlt`` template always ships
      with ``encoding: mlt``), z11–z14 (upstream ceiling; nothing
      renders below z11 — owner decision), no clustering keys anywhere
      (vector tiles sample server-side).
    * a circle layer (z11–z13.99, small, category-colored in the
      seed_lib.TRANSPORT_MODES priority order) hand over to a mono-icon
      symbol layer at z14 (per-mode sprite names where the category tree
      carries a symbol, the generic root silhouette otherwise).
    """

    def test_source_is_mlt_vector_via_martin(self) -> None:
        src = TRANSPORT_STYLE_SUBSET["sources"]["transitland_stops"]
        assert src["type"] == "vector"
        assert src["tiles"] == [
            "{{env:MARTIN_TILE_URL}}/transitland_stops/{z}/{x}/{y}.mlt"
        ]
        # pairing contract (tested for wd-huts/wd-bookings too): a .mlt
        # tiles template always ships with the decoder marker
        assert src["encoding"] == "mlt"
        # z11 = the owner-set floor (nothing renders below); z14 = the
        # Transitland ceiling (deeper zooms overzoom client-side)
        assert src["minzoom"] == 11
        assert src["maxzoom"] == 14
        # no full-only keys in the twin — the fallback document stays
        # Leaflet-renderable end to end
        assert set(src) == {"type", "tiles", "encoding", "minzoom", "maxzoom"}

    def test_sprite_pack_referenced_for_the_icons(self) -> None:
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_ICON_FALLBACK,
            TRANSPORT_ICONS,
            TRANSPORT_SPRITE_ID,
        )

        # OWN sprite id, unique per layer: frontend sprite ids are
        # add-once (first URL wins) — a shared "wd" id let the huts
        # pack shadow this one and the icons silently resolved to
        # nothing (stops vanished at z14+). Every icon name must carry
        # exactly this id's prefix.
        assert TRANSPORT_SPRITE_ID == "wd-transport"
        assert TRANSPORT_SPRITE_ID != "wd"
        # FULL: the SDF pack — runtime-tintable mono silhouettes
        # (icon-color only works on SDF icons; non-SDF renders black)
        assert TRANSPORT_STYLE["sprite"] == [
            {
                "id": TRANSPORT_SPRITE_ID,
                "url": "{{env:MARTIN_TILE_URL}}/sdf_sprite/transport",
            }
        ]
        # TWIN: the regular sprite pack — the fallback renderer cannot
        # tint SDF icons
        assert TRANSPORT_STYLE_SUBSET["sprite"] == [
            {
                "id": TRANSPORT_SPRITE_ID,
                "url": "{{env:MARTIN_TILE_URL}}/sprite/transport",
            }
        ]
        # per-mode icons only for modes with a category symbol, the
        # group's own silhouette as fallback
        assert set(TRANSPORT_ICONS) == {
            "rail",
            "tram",
            "metro",
            "ferry",
            "bus",
        }
        prefix = TRANSPORT_SPRITE_ID + ":"
        assert all(icon.startswith(prefix) for icon in TRANSPORT_ICONS.values())
        assert TRANSPORT_ICON_FALLBACK == prefix + "mono/transport.transport"

    def test_primitives_layer_contract(self) -> None:
        """z11–z13.99 renders PRIMITIVE mode markers, not anonymous dots
        (owner 2026-11-17) — one marker per stop group, collision-active."""
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_MODES,
            TRANSPORT_PRIMITIVE_FALLBACK,
            TRANSPORT_PRIMITIVES,
        )

        band = TRANSPORT_STYLE_SUBSET["layers"][0]
        assert band["id"] == "transport-stops-primitives"
        assert band["type"] == "symbol"
        assert band["source-layer"] == "stops"
        assert band["minzoom"] == 11
        assert band["maxzoom"] == 14  # exclusive: mono icons take over
        assert band["filter"] == [
            "case",
            ["==", ["get", "location_type"], 1],
            True,
            ["!", ["has", "parent_station"]],
            True,
            False,
        ]
        # per-mode primitive sprite names in TRANSPORT_MODES priority
        # order, the root primitive as the fallback — literal names
        # (concat is not subset-whitelisted)
        expr = band["layout"]["icon-image"]
        assert expr[0] == "case"
        assert expr[2:-1:2] == [TRANSPORT_PRIMITIVES[s] for s, _ in TRANSPORT_MODES]
        assert expr[-1] == TRANSPORT_PRIMITIVE_FALLBACK
        # collision-active: NO allow-overlap (the loser hides instead of
        # stacking — owner 2026-11-17)
        assert "icon-allow-overlap" not in band["layout"]
        # small: z11 0.16 → z13 0.28 (48px primitives → 7.7–13.4px)
        size = band["layout"]["icon-size"]
        assert size[3] == 11 and size[4] == 0.16
        assert size[5] == 13 and size[6] == 0.28

    def test_icon_layer_contract(self) -> None:
        """Stations reveal their mono glyph a zoom early (z13); the
        neighborhood band follows at z14; platform detail from z17
        (exclusive handover). The neighborhood band is collision-active
        (no allow-overlap) — platforms keep overlap (they cluster)."""
        by_id = {l["id"]: l for l in TRANSPORT_STYLE_SUBSET["layers"]}

        stations = by_id["transport-stops-icons-stations"]
        assert stations["type"] == "symbol"
        assert stations["minzoom"] == 13
        assert stations["maxzoom"] == 14
        # STATIONS only — the interchange hierarchy gets the mono glyph
        # while plain stops are still primitives
        assert stations["filter"] == ["==", ["get", "location_type"], 1]
        assert "icon-allow-overlap" not in stations["layout"]

        group = by_id["transport-stops-icons"]
        assert group["minzoom"] == 14
        assert group["maxzoom"] == 17
        # one icon per stop group at neighborhood zooms (same filter as
        # the primitives band)
        assert group["filter"] == by_id["transport-stops-primitives"]["filter"]
        assert "icon-allow-overlap" not in group["layout"]
        assert group["layout"]["icon-size"][3] == 14

        detail = by_id["transport-stops-icons-detail"]
        assert detail["minzoom"] == 17
        # platform detail only — the parent station would sit
        # redundantly mid-road between its platforms (the reported
        # "3 icons for 2 bus stops")
        assert detail["filter"] == ["==", ["get", "location_type"], 0]
        # platforms legitimately cluster millimetres apart — overlap OK
        assert detail["layout"]["icon-allow-overlap"] is True
        assert detail["layout"]["icon-size"][3] == 17  # ramp continues

    def test_icon_image_case_chain_uses_literal_names(self) -> None:
        """Per-mode whole literal sprite names (concat is not in the
        subset whitelist) in TRANSPORT_MODES priority order, generic
        root silhouette as the fallback."""
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_FALLBACK_COLORS,
            TRANSPORT_ICON_FALLBACK,
            TRANSPORT_ICONS,
            TRANSPORT_MODES,
        )

        icon_expr = TRANSPORT_STYLE_SUBSET["layers"][1]["layout"]["icon-image"]
        assert icon_expr[0] == "case"
        conditions = icon_expr[1:-1:2]
        values = icon_expr[2:-1:2]
        assert len(conditions) == len(values) == len(TRANSPORT_MODES)
        haystack = ["get", "route_types_basic"]
        for (slug, basic_type), condition, icon in zip(
            TRANSPORT_MODES, conditions, values, strict=True
        ):
            assert icon == TRANSPORT_ICONS.get(slug, TRANSPORT_ICON_FALLBACK)
            assert condition[1] == ["in", f"[{basic_type}]", haystack]
        assert icon_expr[-1] == TRANSPORT_ICON_FALLBACK
        # the color chain keeps the full palette mapping — the tint now
        # lives on the icon bands (FULL doc: SDF icon-color paint)
        bands = {l["id"]: l for l in TRANSPORT_STYLE["layers"] if l["type"] == "symbol"}
        color_expr = bands["transport-stops-primitives"]["paint"]["icon-color"]
        assert color_expr[2:-1:2] == [
            TRANSPORT_FALLBACK_COLORS[slug] for slug, _ in TRANSPORT_MODES
        ]
        assert color_expr[-1] == TRANSPORT_FALLBACK_COLORS["other"]

    def test_full_style_sdf_halo_and_selection_contract(self) -> None:
        """The FULL document carries the hut-style look (owner decision
        2026-11-15): mode-tinted SDF icons with the white halo ladder,
        hover halo recolor, selected plates under both icon bands."""
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_FALLBACK_COLORS,
            TRANSPORT_MODES,
        )

        layers = {layer["id"]: layer for layer in TRANSPORT_STYLE["layers"]}

        # mode tint on both icon bands — the SAME case chain the
        # circles use (map and legend cannot drift apart)
        mode_colors = [TRANSPORT_FALLBACK_COLORS[s] for s, _ in TRANSPORT_MODES]
        for icon_id in ("transport-stops-icons", "transport-stops-icons-detail"):
            paint = layers[icon_id]["paint"]
            assert paint["icon-color"][0] == "case"
            assert paint["icon-color"][2:-1:2] == mode_colors
            assert paint["icon-color"][-1] == TRANSPORT_FALLBACK_COLORS["other"]
            # hover recolors ONLY the halo (mode color); rest stays white
            halo = paint["icon-halo-color"]
            assert halo[0] == "case"
            assert halo[1] == ["boolean", ["feature-state", "hovered"], False]
            assert halo[2][2:-1:2] == mode_colors
            assert halo[-1] == "#ffffff"
            # crisp outline, zoom-scaled width ladder
            assert paint["icon-halo-blur"] == 0
            assert paint["icon-halo-width"][0] == "interpolate"

        # selected plates under BOTH bands — white plate + ring,
        # everything opacity-gated on feature-state selected (the
        # blue-ring-storm lesson: stroke opacity gates separately)
        for plate_id, minzoom in (
            ("transport-stops-selected", 14),
            ("transport-stops-selected-detail", 17),
        ):
            plate = layers[plate_id]
            assert plate["type"] == "circle"
            assert plate["minzoom"] == minzoom
            assert plate["paint"]["circle-color"] == "#ffffff"
            for key in ("circle-opacity", "circle-stroke-opacity"):
                assert plate["paint"][key] == [
                    "case",
                    ["boolean", ["feature-state", "selected"], False],
                    1,
                    0,
                ]
            # FIXED ring accent — never the mode color, so active
            # cannot read as a bigger hover (owner 2026-11-16)
            assert plate["paint"]["circle-stroke-color"] == "#2673bf"

        # z-order: each plate sits BEFORE its icon band
        order = [layer["id"] for layer in TRANSPORT_STYLE["layers"]]
        assert order.index("transport-stops-selected") < order.index(
            "transport-stops-icons"
        )
        assert order.index("transport-stops-selected-detail") < order.index(
            "transport-stops-icons-detail"
        )

        # feature-state needs a stable per-feature id — the full source
        # promotes the Transitland stable key (the #452 lesson); the
        # subset twin must NOT carry it (subset-forbidden)
        assert (
            TRANSPORT_STYLE["sources"]["transitland_stops"]["promoteId"] == "onestop_id"
        )
        assert "promoteId" not in TRANSPORT_STYLE_SUBSET["sources"]["transitland_stops"]

    def test_no_clustering_anywhere(self) -> None:
        for source in TRANSPORT_STYLE["sources"].values():
            for key in (
                "cluster",
                "clusterMaxZoom",
                "clusterRadius",
                "clusterProperties",
            ):
                assert key not in source, key
        assert all("cluster" not in layer["id"] for layer in TRANSPORT_STYLE["layers"])

    def test_db_colors_overlay_the_fallback_palette(self) -> None:
        """map_seed bakes the live transport category rows' colors into
        the paint (legend parity) — transport_style(colors=...) overrides."""
        from server.apps.basemaps.seed_lib import transport_style

        styled = transport_style({"rail": "#ff0000"})
        bands = {l["id"]: l for l in styled["layers"] if l["type"] == "symbol"}
        color_expr = bands["transport-stops-primitives"]["paint"]["icon-color"]
        assert color_expr[2] == "#ff0000"  # rail (first mode) overridden
        assert color_expr[4] != "#ff0000"  # tram keeps the fallback

    def test_style_passes_walker(self) -> None:
        """The subset twin is walker-clean — the whitelist admits
        the vector source keys, the match filter, the case/in/get
        presence paints and the symbol layer's literal icon chain
        (the FULL document legitimately fails: halo paints and
        feature-state are subset-forbidden)."""
        validate_subset_style(TRANSPORT_STYLE_SUBSET)


class HutsIconLadderContractTests(SimpleTestCase):
    """The wd-huts icon ladder must reference SDF sprites only.

    Regression: the far-zoom branch pulled icons from the regular
    ``wd`` primitive sprite. Those SVGs are authored with
    fill="currentColor", which the sprite rasterizer resolves to
    black — and non-SDF icons ignore ``icon-color`` paint anyway — so
    every hut rendered as an untintable black shape below z9. Both
    step branches must stay on ``wd-sdf:`` names so the type color +
    white halo paint applies at every zoom.
    """

    @staticmethod
    def _icon_name_literals(node: Any) -> set[str]:
        """Collect icon-name literals (sprite refs and concat prefixes)."""
        if isinstance(node, str):
            return {node} if ("/" in node or ":" in node) else set()
        if isinstance(node, list):
            names: set[str] = set()
            for child in node:
                names |= HutsIconLadderContractTests._icon_name_literals(child)
            return names
        return set()

    def test_icon_ladder_is_sdf_only(self) -> None:
        layer = next(
            layer for layer in HUTS_STYLE["layers"] if layer["id"] == "wd-huts"
        )
        expr = layer["layout"]["icon-image"]
        assert expr[0] == "step"
        far, near = expr[2], expr[4]
        # far zoom: the primitive shape (simpler at ~5px) ...
        assert self._icon_name_literals(far) == {
            "wd-sdf:primitive/amenity.",
            "wd-sdf:primitive/amenity.accommodation.unknown",
            "wd-sdf:mono/amenity.",
            "wd-sdf:mono/amenity.accommodation.unknown",
        }
        # ... near zoom: the mono glyph
        assert self._icon_name_literals(near) == {
            "wd-sdf:mono/amenity.",
            "wd-sdf:mono/amenity.accommodation.unknown",
            "wd-sdf:primitive/amenity.",
            "wd-sdf:primitive/amenity.accommodation.unknown",
        }
        for branch in (far, near):
            assert all(
                name.startswith("wd-sdf:") for name in self._icon_name_literals(branch)
            )

    def test_halo_paint_present(self) -> None:
        """The white border (halo) paint both zoom branches rely on.

        icon-halo-width is absolute pixels (not scaled by icon-size),
        so it must follow the icon-size ladder: a constant 2px halo
        merged into a white plate around the ~14px mid-zoom glyphs.
        """
        layer = next(
            layer for layer in HUTS_STYLE["layers"] if layer["id"] == "wd-huts"
        )
        paint = layer["paint"]
        assert paint["icon-halo-color"] == "#ffffff"
        # thin at mid zoom, 2px (the owner-approved high-zoom look)
        # from z16
        ladder = paint["icon-halo-width"]
        assert ladder[0] == "interpolate"
        stops = dict(zip(ladder[3::2], ladder[4::2]))
        assert stops == {7: 0.5, 9: 0.75, 11: 1.0, 13: 1.5, 16: 2.0, 20: 2.5}
        # crisp border, no glow
        assert paint["icon-halo-blur"] == 0
        # runtime tint source: per-type color from the tiles
        assert paint["icon-color"][0] == "coalesce"


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
        huts = MapLayer.objects.get(slug="huts", spec="medium", profile="full")
        assert huts.profile == "full"
        assert huts.version == STYLE_SPEC_VERSION
        maptiler = MapLayer.objects.get(slug="maptiler-hybrid", spec="high")
        assert maptiler.profile == "full"
        assert maptiler.version == ""
        # Retagged in place — no orphan full twins beside the subset rows.
        assert not MapLayer.objects.filter(slug="mtb", profile="full").exists()

    def test_transport_stops_single_subset_row_seeded(self) -> None:
        """Owner decision 2026-11-15 (accommodations pattern): the
        overlay seeds a FULL parent — SDF icons, mode tint, halo,
        hover/selection — plus the subset twin (the previous single
        document) for fallback clients."""
        call_command("map_seed", verbosity=0)
        rows = MapLayer.objects.filter(slug="transport-stops")
        assert rows.count() == 2
        full = rows.get(profile="full")
        assert (full.spec, full.profile) == ("medium", "full")
        assert full.min_zoom == 11
        assert full.style is not None
        # the hut-style look: SDF pack, tinted icons, selected plates
        assert full.style["sprite"][0]["url"].endswith("/sdf_sprite/transport")
        assert [layer["id"] for layer in full.style["layers"]] == [
            "transport-stops-primitives",
            "transport-stops-icons-stations",
            "transport-stops-selected",
            "transport-stops-icons",
            "transport-stops-selected-detail",
            "transport-stops-icons-detail",
        ]
        twin = rows.get(profile="subset")
        assert (twin.spec, twin.profile) == ("medium", "subset")
        assert twin.version == SUBSET_REVISION
        assert twin.style is not None
        assert twin.min_zoom == 11
        # primitives z11–z13.99, stations mono a zoom early, then the
        # neighborhood and detail bands
        assert [layer["id"] for layer in twin.style["layers"]] == [
            "transport-stops-primitives",
            "transport-stops-icons-stations",
            "transport-stops-icons",
            "transport-stops-icons-detail",
        ]
        assert twin.style["layers"][0]["minzoom"] == 11
        assert twin.style["layers"][0]["maxzoom"] == 14
        assert twin.style["layers"][1]["minzoom"] == 13
        assert twin.style["layers"][1]["maxzoom"] == 14
        assert twin.style["layers"][2]["minzoom"] == 14
        assert twin.style["layers"][2]["maxzoom"] == 17
        assert twin.style["layers"][3]["minzoom"] == 17
        # slug-level config (filter) rides the row
        assert twin.config is not None
        assert "filters" in twin.config

    def test_huts_subset_variant_seeded(self) -> None:
        """Both huts rows at the same tier; the slug-level config (filters
        + clustering) rides both rows — clustering feeds the fallback's
        own marker rendering; the twin drops the day-strip and selection
        layers and strips promoteId from both sources."""
        call_command("map_seed", verbosity=0)
        full = MapLayer.objects.get(slug="huts", spec="medium", profile="full")
        assert full.version == STYLE_SPEC_VERSION
        subset = MapLayer.objects.get(slug="huts", spec="medium", profile="subset")
        assert subset.version == SUBSET_REVISION
        for row in (full, subset):
            assert row.config is not None
            assert "clustering" in row.config
            assert "filters" in row.config
        assert subset.style is not None
        assert set(subset.style["sources"]) == {"wd-huts", "wd-bookings"}
        assert all(
            "promoteId" not in source for source in subset.style["sources"].values()
        )
        assert [layer["id"] for layer in subset.style["layers"]] == [
            "wd-huts-occupation",
            "wd-huts",
        ]
        # Parameter precedence (variant replaces the parent list): the
        # twin drops the inert icon-scale slider — its baked icon-size
        # ladder never reads the token — and keeps {{date}} for the
        # wd-bookings template; the full row keeps both knobs.
        assert set(full.layer_parameters.values_list("parameter__slug", flat=True)) == {
            "huts.icon_scale",
            "date",
        }
        assert set(
            subset.layer_parameters.values_list("parameter__slug", flat=True)
        ) == {"date"}

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
        huts = MapLayer.objects.get(slug="huts", spec="medium", profile="full")
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
    """dump_map_styles CI-input behavior: written files (FULL and
    SUBSET profiles — both validators see every document since the
    2026-11-06 staging incident), parameter-token resolution, and the
    _skipped.txt manifest for styl-ignored rows."""

    def test_dump_writes_all_profiles_and_ignored_manifest(self, tmp_path: Any) -> None:
        call_command(DumpCommand(), out=str(tmp_path))
        names = sorted(path.name for path in tmp_path.iterdir())
        # Authored full styles without an ignore list are dumped …
        assert "huts--medium--full.json" in names
        # … and so are the subset twins (walker-owned AND validator-
        # owned now: styl + the maplibre validator run over every dump)
        assert "huts--medium--subset.json" in names
        assert "world-topo--high--subset.json" in names
        assert "mtb--medium--subset.json" in names
        assert "transport-stops--medium--subset.json" in names
        assert "restaurant--medium--subset.json" in names
        body = json.loads((tmp_path / "huts--medium--full.json").read_text())
        assert body["version"] == 8
        # styl-ignored (["*"]) rows are STILL WRITTEN + manifested:
        # the styl job skips them via _skipped.txt, but the MapLibre
        # validator needs the real (composed) documents — the basemap
        # blocks only exist in the dump since the serve-time
        # composition landed (owner 2026-11-17).
        assert "world-satellite-hybrid--high--full.json" in names
        assert (
            "wd-outdoor-base-ofm-hill--high--full.json" in names
        )  # styl-skipped basemap, written + composed
        ofm = json.loads(
            (tmp_path / "wd-outdoor-base-ofm-hill--high--full.json").read_text()
        )
        assert any(
            layer["id"].startswith("wd-basemap-transit-")
            for layer in ofm["layers"]
        )
        manifest = (tmp_path / "_skipped.txt").read_text().split()
        assert "world-satellite-hybrid" in manifest
        assert "ch-swisstopo-light" in manifest  # variant-level ["*"]
        assert "ch-swisstopo-full" in manifest
        assert "wd-outdoor-base-ofm-hill" in manifest
        assert "huts" not in manifest

    def test_dump_resolves_parameter_tokens(self, tmp_path: Any) -> None:
        """The dump is the RESOLVED form (frontend validation parity):
        scalar tokens baked to their defaults, opacity-curve tokens to
        their default EXPRESSIONS — styl rejects unresolved token
        strings (E018) and the maplibre validator rejects strings in
        numeric expression slots. ``{{env:…}}``/``{{date}}`` tokens
        embedded in URL strings legitimately stay."""
        call_command(DumpCommand(), out=str(tmp_path))
        huts = (tmp_path / "huts--medium--full.json").read_text()
        assert "{{huts.icon_scale}}" not in huts
        cycling = json.loads((tmp_path / "cycling--medium--subset.json").read_text())
        # the resolved opacity default is an interpolate EXPRESSION
        opacity = cycling["layers"][0]["paint"]["raster-opacity"]
        assert isinstance(opacity, list)
        assert opacity[0] == "interpolate"
        accommodations = (tmp_path / "accommodations--medium--full.json").read_text()
        assert "{{accommodations.icon_scale}}" not in accommodations
        # env/URL-embedded tokens are serve-time, not dump-time
        assert "{{env:MARTIN_TILE_URL}}" in accommodations


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
        assert "promoteId" not in style.json()["sources"]["transitland_stops"]
        assert "transport-stops-icons" in [
            layer["id"] for layer in style.json()["layers"]
        ]
        # Unprofiled requests resolve the FULL parent (the hut-style
        # document); fallback clients ask profile=subset explicitly.
        unprofiled = Client().get("/v1/map/layers/transport-stops")
        assert unprofiled.json()["profile"] == "full"
        assert unprofiled.json()["style_url"].endswith("/sdf_sprite/transport") is (
            False
        )  # sprite lives in the style document, not the URL

    def test_seeded_subset_catalog_includes_huts(self) -> None:
        """Owner decision: the huts overlay appears in the subset catalog
        and becomes menu-toggleable on the Leaflet fallback — the twin
        carries BOTH sources (the fallback reads wd-bookings for
        availability); unprofiled clients keep the full row."""
        call_command("map_seed", verbosity=0)
        response = Client().get("/v1/map/layers?profile=subset")
        assert response.status_code == 200
        entries = {entry["slug"]: entry for entry in response.json()["data"]}
        assert "huts" in entries
        entry = entries["huts"]
        assert entry["profile"] == "subset"
        assert entry["version"] == SUBSET_REVISION
        assert "profile=subset" in entry["style_url"]
        style = Client().get("/v1/map/styles/huts.json?profile=subset")
        assert style.status_code == 200
        body = style.json()
        assert [layer["id"] for layer in body["layers"]] == [
            "wd-huts-occupation",
            "wd-huts",
        ]
        assert set(body["sources"]) == {"wd-huts", "wd-bookings"}
        unprofiled = Client().get("/v1/map/layers/huts")
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


class TransportModeExtrasParityTests(SimpleTestCase):
    """The GTFS↔category pairing exists twice ON PURPOSE: code-side
    (``seed_lib.TRANSPORT_MODES`` — the fast path the style builds from,
    no DB round-trip) and data-side (``categories.0022`` mirrors the
    basic route type into each mode child's ``extra`` under
    ``gtfs_route_type`` — admin/other apps can read it). This test keeps
    the two from drifting apart. Parity is by GTFS CODE: the kind slugs
    were renamed to Transitland basic route type names
    (``categories.0025``), so the historical migration dict carries the
    old slugs while seed_lib carries the new ones — the codes are the
    contract.
    """

    def test_migration_modes_match_seed_lib_table(self) -> None:
        import importlib

        from server.apps.basemaps.seed_lib import TRANSPORT_MODES

        # digit-leading module name — plain import syntax cannot express it
        migration = importlib.import_module(
            "server.apps.categories.migrations.0022_transport_mode_colors"
        )

        # every basic GTFS type is covered on both sides, exactly once
        seed_lib_codes = [code for _slug, code in TRANSPORT_MODES]
        migration_codes = [codes[1] for codes in migration.MODES.values()]
        assert sorted(seed_lib_codes) == sorted(migration_codes)
        assert len(set(seed_lib_codes)) == len(seed_lib_codes)
        # each seed_lib mode carries its historical code under its new slug
        seed_lib_by_code = {code: slug for slug, code in TRANSPORT_MODES}
        for _color, code in migration.MODES.values():
            assert seed_lib_by_code[code], f"code {code} missing in seed_lib"
        # the extras key name is stable API for other readers
        assert migration.GTFS_EXTRA_KEY == "gtfs_route_type"


class TransportBasemapBlockTests(SimpleTestCase):
    """The overlay's BASEMAP presence: "my POIs, not the basemap's"
    (owner 2026-11-17). config.basemap blocks compose into basemap
    documents at SERVE time (and in the CI dump); always-replace rides
    the wd-basemap-<slug>-* layer-id namespace — no replaces list."""

    def test_block_contract(self) -> None:
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_BASEMAP_SPRITE_ID,
            transport_basemap_block,
        )

        block = transport_basemap_block()
        # own sprite id (add-once ids must not collide with the overlay's)
        assert block["sprite"][0]["id"] == TRANSPORT_BASEMAP_SPRITE_ID
        assert block["sprite"][0]["id"] != "wd-transport"
        # namespaced layer ids — the always-replace contract prefix
        ids = [layer["id"] for layer in block["layers"]]
        assert ids == [
            "wd-basemap-transit-stations",
            "wd-basemap-transit-stations-label",
        ]
        # stations only, LATER than the overlay floor (z13 vs z11)
        icon = block["layers"][0]
        assert icon["minzoom"] == 13
        assert icon["filter"] == ["==", ["get", "location_type"], 1]
        # the icon chain uses the BASEMAP sprite prefix, not the overlay's
        names = icon["layout"]["icon-image"][2:-1:2]
        assert names and all(
            n.startswith(TRANSPORT_BASEMAP_SPRITE_ID + ":") for n in names
        )
        # anchors name the freed slots per basemap family
        assert "highway-name-path" in block["insert_before"]
        assert "road_path_oneway_symbol" in block["insert_before"]

    def test_compose_anchors_into_the_freed_slot(self) -> None:
        from server.apps.basemaps.seed_lib import (
            compose_basemap_style,
            transport_basemap_block,
        )

        empty: dict[str, Any] = {}
        doc: dict[str, Any] = {
            "version": 8,
            "sources": {},
            "layers": [
                {"id": "background", "type": "background", "layout": empty},
                {"id": "highway-name-path", "type": "symbol", "layout": empty},
                {"id": "later", "type": "symbol", "layout": empty},
            ],
        }
        out = compose_basemap_style(doc, [transport_basemap_block()])
        ids = [layer["id"] for layer in out["layers"]]
        # inserted BEFORE the anchor — the slot the native POI layer held
        assert ids == [
            "background",
            "wd-basemap-transit-stations",
            "wd-basemap-transit-stations-label",
            "highway-name-path",
            "later",
        ]

    def test_compose_falls_back_to_the_label_band(self) -> None:
        from server.apps.basemaps.seed_lib import (
            compose_basemap_style,
            transport_basemap_block,
        )

        doc: dict[str, Any] = {
            "version": 8,
            "layers": [
                {"id": "bg", "type": "background"},
                {
                    "id": "place-label",
                    "type": "symbol",
                    "layout": {"text-field": "x"},
                },
            ],
        }
        out = compose_basemap_style(doc, [transport_basemap_block()])
        ids = [layer["id"] for layer in out["layers"]]
        assert ids.index("wd-basemap-transit-stations") == 1

    def test_compose_merges_sprite_and_sources_without_collisions(self) -> None:
        from server.apps.basemaps.seed_lib import (
            TRANSPORT_BASEMAP_SPRITE_ID,
            compose_basemap_style,
            transport_basemap_block,
        )

        doc: dict[str, Any] = {
            "version": 8,
            "sprite": [{"id": "ofm", "url": "x"}],
            "sources": {"openmaptiles": {"type": "vector"}},
            "layers": [],
        }
        out = compose_basemap_style(doc, [transport_basemap_block()])
        assert [s["id"] for s in out["sprite"]] == [
            "ofm",
            TRANSPORT_BASEMAP_SPRITE_ID,
        ]
        assert "wd-basemap-transitland-stops" in out["sources"]
        assert "openmaptiles" in out["sources"]


@pytest.mark.django_db
class TransportBasemapServingTests:
    """Serve-time composition: the endpoint serves the composed basemap
    (never the bare fixture), overlays stay un-composed, and the
    immutable version token folds the contributing overlay rows."""

    def test_basemap_style_serves_the_composed_document(self) -> None:
        from django.core.management import call_command

        from server.apps.basemaps.models import MapLayer

        call_command("map_seed", verbosity=0)
        response = Client().get("/v1/map/styles/wd-outdoor-base-ofm.json")
        assert response.status_code == 200
        layers = [layer["id"] for layer in response.json()["layers"]]
        assert "wd-basemap-transit-stations" in layers
        assert "wd-basemap-transit-stations-label" in layers
        # the native transit POIs are gone — ours replace them
        assert "poi_transit" not in layers
        # the injected sprite rides along
        sprites = {s["id"] for s in response.json()["sprite"]}
        assert "wd-basemap-transport" in sprites

        # overlay styles stay un-composed
        overlay = Client().get("/v1/map/styles/transport-stops.json")
        overlay_ids = [layer["id"] for layer in overlay.json()["layers"]]
        assert "wd-basemap-transit-stations" not in overlay_ids

        # the token rotates when a contributing overlay row changes
        before = Client().get("/v1/map/styles/wd-outdoor-base-ofm.json")
        row = MapLayer.objects.filter(
            slug="transport-stops", profile=MapLayer.Profile.full
        ).first()
        assert row is not None
        row.save(update_fields=["modified"])  # bumps modified
        after = Client().get("/v1/map/styles/wd-outdoor-base-ofm.json")
        assert (
            before.headers["X-Map-Style-Version"]
            != after.headers["X-Map-Style-Version"]
        )
