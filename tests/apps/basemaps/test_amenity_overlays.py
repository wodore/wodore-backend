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
                f"wd-{subtree}-cluster-count",
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
