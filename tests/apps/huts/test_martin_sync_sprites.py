"""martin_sync sprite walk: contract groups keep their own collections.

The category tree gained map super-roots (geometries migration 0067:
``map → super-root (amenity/admin/natural) → contract group → kind``).
The sprite walk serves ONE collection per contract group
(``sprites/accommodation/…``, ``sprites/transport/…`` — the names the
served styles reference, e.g. ``/sprite/accommodation,availability`` in
basemaps ``seed_lib``). Icon names are the tree path below ``map``
(``amenity.accommodation.hut``) — vocabulary roots and the map root /
super-roots own no collection. These tests pin that layout.

pytest-function style on purpose: the tmp-media fixture (keeps symbol
SVGs out of the repo checkout) is an autouse pytest fixture and does
not reach unittest.TestCase methods.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from pytest_django.fixtures import SettingsWrapper

from django.core.files.base import ContentFile

from server.apps.categories.models import Category
from server.apps.huts.management.commands.martin_sync import Command
from server.apps.licenses.models import License
from server.apps.symbols.models import Symbol

VARIANTS = ["color"]


def _stats() -> dict[str, Any]:
    """Same counters ``handle()`` initializes (see test_martin_sync_config)."""
    return {
        "files_copied": 0,
        "files_updated": 0,
        "files_created": 0,
        "bytes_copied": 0,
        "files_skipped": 0,
        "categories_processed": 0,
        "categories_skipped": 0,
        "errors": 0,
        "config_changed": False,
        "files_deleted": 0,
        "sprite_dirs": [],
    }


@pytest.fixture(autouse=True)
def _tmp_media(settings: SettingsWrapper, tmp_path: Path):
    """Keep symbol SVG files out of the repo checkout."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def map_tree(db: None) -> dict[str, Category]:
    """Post-0067-shaped tree: map root, super-root, groups, kinds, vocab root.

    Every category carries a color symbol so each produces a sprite
    file; identifiers land as in production (``accommodation.hut``,
    ``root.spot`` … — parent-relative, two segments).
    """
    license_ = License.objects.create(slug="test-license", name="Test")

    def category(slug: str, parent: Category | None) -> Category:
        symbol = Symbol(slug=f"{slug}-color", search_text=slug, license=license_)
        symbol.svg_file.save(f"color__{slug}.svg", ContentFile(b"<svg/>"), save=True)
        return Category.objects.create(
            slug=slug,
            parent=parent,
            name=slug,
            is_active=True,
            symbol_color=symbol,
        )

    map_root = category("map", None)
    amenity = category("amenity", map_root)
    accommodation = category("accommodation", amenity)
    hut = category("hut", accommodation)
    transport = category("transport", amenity)
    # vocabulary root — must NOT become a sprite collection anymore
    spot = category("spot", None)
    castle = category("castle", spot)
    return {
        "map": map_root,
        "amenity": amenity,
        "accommodation": accommodation,
        "hut": hut,
        "transport": transport,
        "spot": spot,
        "castle": castle,
    }


def _run_sync(
    tmp: Path, include: list[str] | None = None
) -> tuple[dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    command = Command(stdout=out, stderr=err)
    stats = _stats()
    command._cleanup_old_sprites(tmp, False, stats, include, VARIANTS, Category)
    command._sync_sprites(tmp, False, stats, include, VARIANTS, Category)
    return stats, out.getvalue() + err.getvalue()


def test_contract_group_is_its_own_collection(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    stats, _ = _run_sync(tmp_path)

    sprites = tmp_path / "sprites"
    assert (sprites / "accommodation/color/amenity.accommodation.svg").is_file()
    assert (sprites / "accommodation/color/amenity.accommodation.hut.svg").is_file()
    assert (sprites / "transport/color/amenity.transport.svg").is_file()
    assert set(stats["sprite_dirs"]) >= {"accommodation", "transport"}


def test_icon_names_are_the_tree_path_below_map(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    """``<domain>.<group>`` / ``<domain>.<group>.<kind>``, derived from
    the live tree — a group move between super-roots renames its icons
    without a martin_sync change (the ``root.<slug>`` era names and the
    collapsed ``map/`` layout are gone)."""
    _run_sync(tmp_path)

    sprites = tmp_path / "sprites"
    # the group's own icon is its identifier: <domain>.<group>
    assert (sprites / "transport/color/amenity.transport.svg").is_file()
    # the pre-restructure-era name is gone
    assert not (sprites / "transport/color/root.transport.svg").exists()
    assert not (sprites / "accommodation/color/root.accommodation.svg").exists()


def test_map_root_super_roots_and_vocab_roots_get_no_collection(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    stats, _ = _run_sync(tmp_path)

    sprites = tmp_path / "sprites"
    assert not (sprites / "map").exists()
    assert not (sprites / "amenity").exists()
    # vocabulary roots (spot/mode/relations/…) are outside the map tree
    assert not (sprites / "spot").exists()
    assert "spot" not in stats["sprite_dirs"]


def test_include_filters_collections(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    stats, _ = _run_sync(tmp_path, include=["accommodation"])

    sprites = tmp_path / "sprites"
    assert (sprites / "accommodation/color/amenity.accommodation.hut.svg").is_file()
    assert not (sprites / "transport").exists()
    assert not (sprites / "spot").exists()
    assert set(stats["sprite_dirs"]) == {"accommodation"}


def test_sprite_files_are_sanitized_for_martin(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    """The staging incident: DB symbols carrying lxml ``ns0:`` prefixes
    or a root without ``xmlns`` must reach the sprite directory in the
    default SVG namespace — Martin 1.16's strict XML parser rejects both
    shapes with ``NoRootNode`` (until now patched by hand on the PVC)."""
    dirty_ns0 = (
        b'<svg xmlns:ns0="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        b'<ns0:path d="M0 0h24v24H0z"/></svg>'
    )
    dirty_bare = b'<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
    hut_symbol = map_tree["hut"].symbol_color
    group_symbol = map_tree["accommodation"].symbol_color
    assert hut_symbol is not None and group_symbol is not None
    hut_symbol.svg_file.save("color__hut.svg", ContentFile(dirty_ns0), save=True)
    group_symbol.svg_file.save(
        "color__accommodation.svg", ContentFile(dirty_bare), save=True
    )

    _run_sync(tmp_path)

    sprites = tmp_path / "sprites"
    hut_sprite = (
        sprites / "accommodation/color/amenity.accommodation.hut.svg"
    ).read_bytes()
    group_sprite = (
        sprites / "accommodation/color/amenity.accommodation.svg"
    ).read_bytes()
    assert b"ns0" not in hut_sprite
    assert hut_sprite.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    assert group_sprite.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')


def test_cleanup_removes_collapsed_map_dir_and_stale_files(
    tmp_path: Path, map_tree: dict[str, Category]
) -> None:
    """The staging regression: files left by the collapsed ``map/`` walk
    (and stale kind files) are pruned, current files stay."""
    _run_sync(tmp_path)

    sprites = tmp_path / "sprites"
    stale_map = sprites / "map/color/root.map.svg"
    stale_super = sprites / "map/color/map.amenity.svg"
    stale_kind = sprites / "accommodation/color/accommodation.hotel.svg"
    stale_root_name = sprites / "transport/color/root.transport.svg"
    for path in (stale_map, stale_super, stale_kind, stale_root_name):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"<svg stale/>")

    stats, _ = _run_sync(tmp_path)

    assert not stale_map.exists()
    assert not stale_super.exists()
    assert not stale_kind.exists()
    assert not stale_root_name.exists()
    assert (sprites / "accommodation/color/amenity.accommodation.hut.svg").is_file()
    assert stats["files_deleted"] == 4
