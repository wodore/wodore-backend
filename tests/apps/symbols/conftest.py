"""Shared fixtures for the symbols app tests (openspec: icon-library)."""

import json
from pathlib import Path

import pytest

SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<circle cx='50' cy='50' r='40' fill='red'/></svg>"
)


def _write(path: Path, content: str | dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def _fluent_entry(hexcode: str, label: str, group: int, subgroup: int, order: int):
    return {
        "label": label,
        "hexcode": hexcode,
        "tags": [],
        "type": 1,
        "order": order,
        "group": group,
        "subgroup": subgroup,
    }


@pytest.fixture
def emoji_fixture(tmp_path: Path) -> Path:
    """Small upstream-shaped tree: 4 fluent folders + 3 noto SVGs.

    Mirrors the real layouts (see test_icon_import for details).
    """
    root = tmp_path

    # --- fluent ---
    fluent = root / "fluent" / "assets"
    for folder, styles in (
        ("Tent", ("Color", "Flat", "High Contrast")),
        ("Red Heart", ("Color", "Flat", "High Contrast")),
    ):
        for style in styles:
            key = style.lower().replace(" ", "_")
            _write(fluent / folder / style / f"{key}.svg", SVG)
    _write(
        fluent / "Tent" / "metadata.json",
        {"cldr": "tent", "tts": "tent", "unicode": "26fa"},
    )
    _write(
        fluent / "Red Heart" / "metadata.json",
        {"cldr": "red-heart", "tts": "red heart", "unicode": "2764"},
    )

    # Skin-tone layout: assets/<Name>/Default/<Style>/x.svg
    for style in ("Color", "Flat", "High Contrast"):
        key = style.lower().replace(" ", "_")
        _write(fluent / "Hiking Boot" / "Default" / style / f"{key}.svg", SVG)
    _write(
        fluent / "Hiking Boot" / "metadata.json",
        {"cldr": "hiking boot", "tts": "hiking boot", "unicode": "1f97e"},
    )

    # Unmatched upstream icon (no emojibase entry: e000 is private-use).
    _write(fluent / "Brand Logo" / "Color" / "brand_logo.svg", SVG)
    _write(
        fluent / "Brand Logo" / "metadata.json",
        {"cldr": "brand-logo", "tts": "brand logo", "unicode": "e000"},
    )

    # --- noto ---
    noto = root / "noto" / "2D" / "svg"
    for codepoints in ("26fa", "1f97e", "0023"):
        _write(noto / f"emoji_u{codepoints}.svg", SVG)

    # --- emojibase ---
    base = root / "emojibase"
    _write(
        base / "meta" / "groups.json",
        {
            "groups": {
                "1": "people-body",
                "2": "component",
                "5": "travel-places",
                "7": "objects",
            },
            "hierarchy": {"1": [12], "2": [], "5": [53], "7": [65]},
        },
    )
    en_data = [
        {
            "label": "tent",
            "hexcode": "26FA",
            "tags": ["camping"],
            "type": 1,
            "order": 3522,
            "group": 5,
            "subgroup": 53,
        },
        _fluent_entry("2764-FE0F", "red heart", 1, 12, 918),
        {
            "label": "hiking boot",
            "hexcode": "1F97E",
            "tags": ["boot", "hiking"],
            "type": 1,
            "order": 1234,
            "group": 7,
            "subgroup": 65,
        },
        # Component entries (ZWJ etc., `component` group) are skipped by
        # the import — NOT via the `type` field (that is presentation
        # metadata and marks real emoji like camping as type 0).
        {"label": "zero width joiner", "hexcode": "200D", "group": 2},
    ]
    de_data = [
        {
            "label": "Zelt",
            "hexcode": "26FA",
            "tags": ["campen", "zelten"],
            "type": 1,
            "order": 3522,
            "group": 5,
            "subgroup": 53,
        },
        {"label": "rotes Herz", "hexcode": "2764-FE0F", "tags": [], "type": 1},
        {
            "label": "Wanderschuh",
            "hexcode": "1F97E",
            "tags": ["wandern"],
            "type": 1,
            "order": 1234,
            "group": 7,
            "subgroup": 65,
        },
    ]
    _write(base / "en" / "data.json", en_data)
    _write(base / "de" / "data.json", de_data)

    en_messages = {
        "groups": [
            {"key": "people-body", "message": "people & body", "order": 1},
            {"key": "travel-places", "message": "travel & places", "order": 5},
            {"key": "objects", "message": "objects", "order": 7},
        ],
        "subgroups": [
            {"key": "hands", "message": "hands", "order": 12},
            {"key": "place-other", "message": "other places", "order": 53},
            {"key": "clothing", "message": "clothing", "order": 65},
        ],
    }
    de_messages = {
        "groups": [
            {"key": "people-body", "message": "Menschen & Körper", "order": 1},
            {"key": "travel-places", "message": "Reisen & Orte", "order": 5},
            {"key": "objects", "message": "Objekte", "order": 7},
        ],
        "subgroups": [
            {"key": "hands", "message": "Hände", "order": 12},
            {"key": "place-other", "message": "andere Orte", "order": 53},
            {"key": "clothing", "message": "Kleidung", "order": 65},
        ],
    }
    _write(base / "en" / "messages.json", en_messages)
    _write(base / "de" / "messages.json", de_messages)
    return root


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Keep imported SVG files out of the repo checkout."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def imported_db(emoji_fixture):
    """Run the import (both packs, one invocation per source)."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    for source, ref in (("fluent", "test-ref"), ("noto", "noto-ref")):
        call_command(
            "icon_import",
            "--source",
            source,
            "--ref",
            ref,
            "--locales",
            "de,en",
            "--data-dir",
            str(emoji_fixture),
            stdout=out,
        )
    return out.getvalue()
