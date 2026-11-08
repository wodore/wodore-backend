"""Amenity overlay family: importance bands, tile contract, sprites.

The ten non-accommodation amenity overlays are generated from
``seed_lib.AMENITY_OVERLAYS`` specs — these tests pin the band matrix
(importance-scaled min_zoom / cluster_max_zoom / max_label_zoom per
tier), the geoplaces tile-URL contract per subtree, the per-subtree
sprite fallback, and that every subset twin stays walker-clean while
the full documents keep their (deliberate) full-profile-only
expressions.
"""

from __future__ import annotations

from typing import Any

import pytest

from django.test import SimpleTestCase

from server.apps.basemaps import seed_lib as lib
from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.validation import StyleValidationError, validate_subset_style

#: The band matrix (importance-scaled, see the AMENITY_OVERLAYS
#: docstring for the staging counts/averages behind it).
EXPECTED_BANDS: dict[str, tuple[int, int, int]] = {
    # tier A (avg importance >= 50): accommodation parity
    "restaurant": (5, 7, 11),
    "health_and_emergency": (5, 7, 11),
    "outdoor_services": (5, 7, 11),
    # tier B (~30-50): appear mid-zoom, individual by z12
    "groceries": (9, 9, 11),
    "shopping": (9, 9, 11),
    "tourism": (9, 9, 11),
    "services": (9, 9, 11),
    "finance": (9, 9, 11),
    # tier C (< 30): close-up only (toilets, parking)
    "utilities": (13, 11, 13),
    "automotive": (13, 11, 13),
}


class AmenityBandTests(SimpleTestCase):
    def test_all_ten_subtrees_present(self) -> None:
        assert set(lib.AMENITY_OVERLAYS) == set(EXPECTED_BANDS)

    def test_bands_match_tiers(self) -> None:
        for subtree, (floor, cmz, label) in EXPECTED_BANDS.items():
            spec = lib.AMENITY_OVERLAYS[subtree]
            assert spec.min_zoom == floor, subtree
            assert spec.cluster_max_zoom == cmz, subtree
            assert spec.max_label_zoom == label, subtree

    def test_orders_are_unique(self) -> None:
        orders = [spec.order for spec in lib.AMENITY_OVERLAYS.values()]
        assert len(orders) == len(set(orders))


class AmenityStyleContractTests(SimpleTestCase):
    """One sweep per subtree over the generated full document."""

    def test_tile_url_carries_subtree_filter_and_band_params(self) -> None:
        for subtree, (floor, cmz, label) in EXPECTED_BANDS.items():
            style = lib.AMENITY_OVERLAY_STYLES[subtree]
            source = style["sources"][f"wd-{subtree}"]
            template: str = source["tiles"][0]
            assert template.split("?", 1)[0].endswith(".mlt"), subtree
            assert f"category_tree={subtree}" in template, subtree
            assert f"cluster_max_zoom={cmz}" in template, subtree
            assert f"max_label_zoom={label}" in template, subtree
            assert "cache_ttl_days=1" in template, subtree
            assert "fields=color,parent_color,parent_slug," in template, subtree

    def test_tile_url_fields_carry_popup_props(self) -> None:
        """Amenity popups render from tile properties: elevation and
        the per-kind icon key (category_identifier) ride the fields
        list (opt-in in the tile function — migration 0077)."""
        for subtree in EXPECTED_BANDS:
            for styles in (
                lib.AMENITY_OVERLAY_STYLES,
                lib.AMENITY_OVERLAY_STYLES_SUBSET,
            ):
                template: str = styles[subtree]["sources"][f"wd-{subtree}"]["tiles"][0]
                assert "category_identifier" in template, subtree
                assert "elevation" in template, subtree

    def test_source_zooms_match_tier(self) -> None:
        for subtree, (floor, _cmz, _label) in EXPECTED_BANDS.items():
            source = lib.AMENITY_OVERLAY_STYLES[subtree]["sources"][f"wd-{subtree}"]
            assert source["minzoom"] == floor, subtree
            assert source["maxzoom"] == 14, subtree
            assert source["encoding"] == "mlt", subtree
            assert source["promoteId"] == "slug", subtree

    def test_layer_floors_match_tier(self) -> None:
        for subtree, (floor, _cmz, _label) in EXPECTED_BANDS.items():
            style = lib.AMENITY_OVERLAY_STYLES[subtree]
            by_id = {layer["id"]: layer for layer in style["layers"]}
            for layer_id in (
                f"wd-{subtree}-clusters",
                f"wd-{subtree}",
            ):
                assert by_id[layer_id]["minzoom"] == floor, layer_id
            assert set(style["metadata"]["wd:slot_layers"]) == set(by_id)

    def test_sprite_is_per_subtree_with_root_fallback(self) -> None:
        """Each overlay loads its OWN sprite id (sprite ids are add-once
        on the frontend — transport lesson) and every icon lookup
        coalesces to the subtree ROOT icon, so markers render even
        where the subtree's leaf icons are missing."""
        for subtree in EXPECTED_BANDS:
            style = lib.AMENITY_OVERLAY_STYLES[subtree]
            entry = style["sprite"][0]
            assert entry["id"] == f"wd-sdf-{subtree}", subtree
            assert entry["url"].endswith(f"/sdf_sprite/{subtree}"), subtree
            symbol = next(
                layer for layer in style["layers"] if layer["id"] == f"wd-{subtree}"
            )
            fallbacks = _fallbacks(symbol["layout"]["icon-image"])
            assert f"wd-sdf-{subtree}:mono/amenity.{subtree}" in fallbacks, subtree

    def test_label_step_at_max_label_zoom(self) -> None:
        for subtree, (_floor, _cmz, label) in EXPECTED_BANDS.items():
            symbol = next(
                layer
                for layer in lib.AMENITY_OVERLAY_STYLES[subtree]["layers"]
                if layer["id"] == f"wd-{subtree}"
            )
            assert symbol["paint"]["text-opacity"] == [
                "step",
                ["zoom"],
                0,
                label,
                1,
            ], subtree

    def test_cluster_nodes_are_count_scaled_icons(self) -> None:
        """Cluster nodes render the SAME per-kind icon as individuals,
        scaled by member count (1.1× at 2 → 1.8× at ≥ 12, clamped) —
        no count labels, no bubbles (membership comes from
        /v1/geoplaces/near on click)."""
        for subtree in EXPECTED_BANDS:
            full = lib.AMENITY_OVERLAY_STYLES[subtree]
            by_id = {layer["id"]: layer for layer in full["layers"]}
            cluster = by_id[f"wd-{subtree}-clusters"]
            assert cluster["type"] == "symbol", subtree
            assert f"wd-{subtree}-cluster-count" not in by_id, subtree
            size = cluster["layout"]["icon-size"]
            # TOP-LEVEL zoom interpolate (the only legal zoom shape —
            # see test_no_zoom_outside_toplevel_interpolate) with
            # per-stop values ["*", base, count-scale]
            assert size[0] == "interpolate" and size[2] == ["zoom"], subtree
            stops = [float(stop) for stop in size[3::2]]
            values = size[4::2]
            # stops strictly ascending (MapLibre hard parse error)
            assert stops == sorted(stops) and len(set(stops)) == len(stops), subtree
            for value in values:
                assert value[0] == "*", (subtree, value)
                count_scale = value[2]
                # count scale: 1 → 1.0 (singles), 2 → 1.1,
                # 12 → 1.8 (MapLibre clamps beyond)
                assert count_scale[2] == ["get", "count"], subtree
                assert count_scale[3::2] == [1, 2, 12], subtree
                assert count_scale[4::2] == [1.0, 1.1, 1.8], subtree

    def test_no_zoom_outside_toplevel_interpolate(self) -> None:
        """MapLibre's expression spec: ["zoom"] may ONLY be the input
        of a TOP-LEVEL step/interpolate — anywhere else the whole
        document is rejected (staging incident 2026-11-06: all eleven
        full-profile POI overlays served "invalid style documents"
        after an icon-size ``["*", zoom-ladder, count-scale]`` product;
        styl's ruleset did not flag it, the frontend validator did).
        This walker enforces the rule on every generated document."""

        def assert_zoom_legal(expr: Any, top: bool, path: str) -> None:
            if not isinstance(expr, list):
                return
            if expr and expr[0] in ("interpolate", "step"):
                if expr[2] == ["zoom"]:  # legal exactly here, at top
                    assert top, f"zoom-interpolate nested at {path}"
                for child in expr[3:]:
                    assert_zoom_legal(child, False, path)
                return
            for child in expr:
                if child == ["zoom"]:
                    msg = f"bare zoom outside top-level input at {path}"
                    assert top, msg
                else:
                    assert_zoom_legal(child, False, path)

        documents = {
            "accommodations": lib.ACCOMMODATIONS_STYLE,
            "accommodations-subset": lib.ACCOMMODATIONS_STYLE_SUBSET,
            **lib.AMENITY_OVERLAY_STYLES,
            **{f"{k}-subset": v for k, v in lib.AMENITY_OVERLAY_STYLES_SUBSET.items()},
        }
        # LAYOUT only: zoom is legal there exclusively as the input of
        # a TOP-LEVEL step/interpolate (the incident class). PAINT
        # allows broader zoom usage (case-wrapped camera expressions
        # are valid) — the authoritative validator in CI covers paint.
        for name, style in documents.items():
            for layer in style["layers"]:
                for key, expr in (layer.get("layout") or {}).items():
                    assert_zoom_legal(expr, True, f"{name}:{layer['id']}.{key}")

    def test_marker_interaction_contract(self) -> None:
        """Design-review contract (2026-11-07): decluttering sorts
        ASCENDING (importance NEGATED), hover lives in PAINT props only
        (feature-state is illegal in layout like icon-size), the
        selection plate is a white circle with a category ring, and a
        declutter-proof selected-icon twin sits on top."""
        for subtree in EXPECTED_BANDS:
            style = lib.AMENITY_OVERLAY_STYLES[subtree]
            by_id = {layer["id"]: layer for layer in style["layers"]}
            for layer_id in (f"wd-{subtree}-clusters", f"wd-{subtree}"):
                layer = by_id[layer_id]
                layout = layer["layout"]
                # collision-aware: no forced overlap; importance negated
                assert "icon-allow-overlap" not in layout, (subtree, layer_id)
                assert layout["symbol-sort-key"] == [
                    "-",
                    0,
                    ["get", "importance"],
                ], (subtree, layer_id)
                # hover: paint-only feature-state. Clusters wrap a
                # constant in one case; the raw layer's zoom ladder
                # rebuilds PER-STOP (zoom may only feed a top-level
                # interpolate — a case around the ladder is invalid).
                opacity = layer["paint"]["icon-opacity"]
                if layer_id.endswith("-clusters"):
                    assert opacity[0] == "case", subtree
                else:
                    assert opacity[0] == "interpolate", subtree
                    for value in opacity[4::2]:
                        assert value[0] == "case", subtree
                assert layer["paint"]["icon-halo-width"][0] == "interpolate"
            # selection plate
            plate = by_id[f"wd-{subtree}-selected"]
            paint = plate["paint"]
            assert paint["circle-color"] == "#ffffff", subtree
            assert paint["circle-blur"] == 0, subtree
            assert paint["circle-opacity"][0] == "case", subtree
            assert paint["circle-stroke-color"][0] == "case", subtree
            # the ring storm regression: stroke opacity MUST be gated —
            # it defaults to 1 and renders for EVERY feature regardless
            # of circle-opacity (2026-11-07 staging incident)
            assert paint["circle-stroke-opacity"][0] == "case", subtree
            assert paint["circle-stroke-opacity"][5] == 0, subtree
            # radius per-stop values scale by the count factor
            radius = paint["circle-radius"]
            assert radius[2] == ["zoom"], subtree
            assert radius[4][0] == "*", subtree
            # declutter-proof selected icon on top
            sel_icon = by_id[f"wd-{subtree}-selected-icon"]
            assert sel_icon["filter"] == ["==", ["get", "slug"], ""], subtree
            assert sel_icon["layout"]["icon-allow-overlap"] is True, subtree

    def test_accommodations_overlap_exemption_from_z11(self) -> None:
        """The owner exemption: accommodations always visible from z11
        (``icon-overlap`` zoom step), everywhere else collision-aware."""
        style = lib.ACCOMMODATIONS_STYLE
        by_id = {layer["id"]: layer for layer in style["layers"]}
        for layer_id in (
            "wd-accommodations-clusters",
            "wd-accommodations",
        ):
            assert by_id[layer_id]["layout"]["icon-overlap"] == [
                "step",
                ["zoom"],
                "never",
                11,
                "always",
            ], layer_id

    def test_subset_cluster_icons_oversize_raw_ladder(self) -> None:
        """Subset twins: static-sprite cluster icons at a strictly
        ascending zoom ladder (count-independent — the whitelist has
        no ``*``)."""
        for subtree in EXPECTED_BANDS:
            subset = lib.AMENITY_OVERLAY_STYLES_SUBSET[subtree]
            by_id = {layer["id"]: layer for layer in subset["layers"]}
            cluster = by_id[f"wd-{subtree}-clusters"]
            assert cluster["type"] == "symbol", subtree
            size = cluster["layout"]["icon-size"]
            stops = [float(stop) for stop in size[3::2]]
            assert size[2] == ["zoom"], subtree
            assert stops == sorted(stops) and len(set(stops)) == len(stops), subtree
            raw = by_id[subtree if subtree.startswith("wd-") else f"wd-{subtree}"]
            assert stops[0] > raw["layout"]["icon-size"][4], subtree


def _fallbacks(expression: Any) -> set[str]:
    """Static ``image`` literals inside an icon expression tree."""
    found: set[str] = set()
    if isinstance(expression, list):
        if (
            len(expression) == 2
            and expression[0] == "image"
            and isinstance(expression[1], str)
        ):
            found.add(expression[1])
        for child in expression:
            found |= _fallbacks(child)
    return found


class AmenitySubsetProfileTests(SimpleTestCase):
    def test_every_subset_twin_passes_the_walker(self) -> None:
        for subset in lib.AMENITY_OVERLAY_STYLES_SUBSET.values():
            validate_subset_style(subset)

    def test_every_full_document_fails_the_walker(self) -> None:
        """Icon ladder (concat/image/coalesce), count labels (to-string)
        and the feature-state selection circle are full-profile only —
        the twins must stay the subset surface (accommodations
        pattern)."""
        for style in lib.AMENITY_OVERLAY_STYLES.values():
            with pytest.raises(StyleValidationError):
                validate_subset_style(style)


class AmenitySeedEntryTests(SimpleTestCase):
    def test_catalog_entries_exist_for_all_subtrees(self) -> None:
        from server.apps.basemaps.management.commands.map_seed import LAYERS

        by_slug = {entry["slug"]: entry for entry in LAYERS}
        for subtree, spec in lib.AMENITY_OVERLAYS.items():
            entry = by_slug.get(subtree)
            assert entry is not None, subtree
            assert entry["min_zoom"] == spec.min_zoom, subtree
            assert entry["order"] == spec.order, subtree
            assert entry["icon"] == spec.icon, subtree
            assert entry["style"] is lib.AMENITY_OVERLAY_STYLES[subtree], subtree
            assert (
                entry["variants"][0]["style"]
                is (lib.AMENITY_OVERLAY_STYLES_SUBSET[subtree])
            ), subtree
            assert entry["categories"] == [
                {"slug": subtree, "use": "filter"},
                {"slug": subtree, "use": "legend"},
            ], subtree
            # Server-side clustering — a client hint would double-cluster
            assert "clustering" not in entry["config"], subtree

    def test_every_overlay_icon_is_a_backend_ref(self) -> None:
        """ALL overlays (POI family and the raster/vector classics)
        carry pack/slug@mono backend icon refs — the toggle renders
        them through GET /v1/icons (frontend WdBackendIcon); no
        frontend asset names remain."""
        import re

        from server.apps.basemaps.management.commands.map_seed import LAYERS

        overlays = [
            entry for entry in LAYERS if entry.get("role") == MapLayer.Role.overlay
        ]
        assert len(overlays) >= 20
        for entry in overlays:
            icon = entry["icon"]
            assert re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+@mono", icon), (
                entry["slug"],
                icon,
            )
            assert icon.startswith("fluent-emoji/"), (entry["slug"], icon)

    def test_poi_overlays_carry_category_legends(self) -> None:
        """Every POI overlay seeds a category-driven legend section (the
        huts/accommodations shape): the section binds the subtree GROUP
        category — slugs collide across branches (the stray
        'restaurant' leaf), and the group is the category WITH kind
        children, so the catalog payload carries them and the frontend
        legend renders type symbols (2026-11-07: filters shipped, the
        legend payload was null because the lookup matched roots only
        and the ten subtrees had no LEGENDS entries at all)."""
        from server.apps.basemaps.management.commands.map_seed import LEGENDS

        poi_slugs = ["accommodations", *lib.AMENITY_OVERLAYS]
        for slug in poi_slugs:
            definition = LEGENDS.get(slug)
            assert definition is not None, slug
            (section,) = definition["sections"]
            assert section["type"] == "symbol_mono", slug
            assert section["category"] == (
                slug if slug != "accommodations" else "accommodation"
            ), slug
