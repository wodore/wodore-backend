"""Shared fixtures for the symbols app tests (openspec: icon-library)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_django.fixtures import SettingsWrapper

SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<circle cx='50' cy='50' r='40' fill='red'/></svg>"
)


def _write(path: Path, content: str | dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def _fluent_entry(hexcode: str, label: str, group: int, subgroup: int, order: int):
    return {
        "label": label,
        "hexcode": hexcode,
        "tags": list[str](),
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

    # Noto country flags: waved emoji artwork under third_party (the
    # 2D set itself carries no flags — flags ship flagsonly).
    waved = root / "noto" / "third_party" / "region-flags" / "waved-svg"
    _write(waved / "emoji_u1f1e8_1f1ed.svg", SVG)  # flag: Switzerland
    _write(
        waved / "emoji_u1f3f4_e0067_e0062_e0065_e006e_e0067_e007f.svg",
        SVG,
    )  # flag: England (subdivision tag sequence)

    # --- flag-icons (two ratios per code) ---
    for ratio in ("4x3", "1x1"):
        _write(root / "flag-icons" / "flags" / ratio / "ch.svg", SVG)
        # Regional flag without a Unicode emoji equivalent: skipped.
        _write(root / "flag-icons" / "flags" / ratio / "es-ct.svg", SVG)

    # --- circle-flags (round, top-level country codes only) ---
    circle = root / "circle-flags" / "flags"
    _write(circle / "ch.svg", SVG)
    _write(circle / "gb-eng.svg", SVG)
    # Variants/language flags: no emoji mapping / not walked.
    _write(circle / "us-confederate_battle.svg", SVG)
    _write(circle / "language" / "en-us.svg", SVG)

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
                "9": "flags",
            },
            "hierarchy": {"1": [12], "2": [], "5": [53], "7": [65], "9": [251, 252]},
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
        # Emoji country flags (regional-indicator pair + tag sequence).
        {
            "label": "flag: Switzerland",
            "hexcode": "1F1E8-1F1ED",
            "tags": ["swiss"],
            "type": 1,
            "order": 4600,
            "group": 9,
            "subgroup": 251,
        },
        {
            "label": "flag: England",
            "hexcode": "1F3F4-E0067-E0062-E0065-E006E-E0067-E007F",
            "tags": list[str](),
            "type": 1,
            "order": 4601,
            "group": 9,
            "subgroup": 252,
        },
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
        {"label": "rotes Herz", "hexcode": "2764-FE0F", "tags": list[str](), "type": 1},
        {
            "label": "Wanderschuh",
            "hexcode": "1F97E",
            "tags": ["wandern"],
            "type": 1,
            "order": 1234,
            "group": 7,
            "subgroup": 65,
        },
        {
            "label": "Fahne: Schweiz",
            "hexcode": "1F1E8-1F1ED",
            "tags": list[str](),
            "type": 1,
            "order": 4600,
            "group": 9,
            "subgroup": 251,
        },
        {
            "label": "Fahne: England",
            "hexcode": "1F3F4-E0067-E0062-E0065-E006E-E0067-E007F",
            "tags": list[str](),
            "type": 1,
            "order": 4601,
            "group": 9,
            "subgroup": 252,
        },
    ]
    _write(base / "en" / "data.json", en_data)
    _write(base / "de" / "data.json", de_data)

    en_messages = {
        "groups": [
            {"key": "people-body", "message": "people & body", "order": 1},
            {"key": "travel-places", "message": "travel & places", "order": 5},
            {"key": "objects", "message": "objects", "order": 7},
            {"key": "flags", "message": "flags", "order": 9},
        ],
        "subgroups": [
            {"key": "hands", "message": "hands", "order": 12},
            {"key": "place-other", "message": "other places", "order": 53},
            {"key": "clothing", "message": "clothing", "order": 65},
            {"key": "country-flag", "message": "country-flag", "order": 251},
            {"key": "subdivision-flag", "message": "subdivision-flag", "order": 252},
        ],
    }
    de_messages = {
        "groups": [
            {"key": "people-body", "message": "Menschen & Körper", "order": 1},
            {"key": "travel-places", "message": "Reisen & Orte", "order": 5},
            {"key": "objects", "message": "Objekte", "order": 7},
            {"key": "flags", "message": "Flaggen", "order": 9},
        ],
        "subgroups": [
            {"key": "hands", "message": "Hände", "order": 12},
            {"key": "place-other", "message": "andere Orte", "order": 53},
            {"key": "clothing", "message": "Kleidung", "order": 65},
            {"key": "country-flag", "message": "Landesflagge", "order": 251},
            {
                "key": "subdivision-flag",
                "message": "Flagge der Untergliederung",
                "order": 252,
            },
        ],
    }
    _write(base / "en" / "messages.json", en_messages)
    _write(base / "de" / "messages.json", de_messages)
    return root


@pytest.fixture(autouse=True)
def _tmp_media(settings: SettingsWrapper, tmp_path: Path):
    """Keep imported SVG files out of the repo checkout."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def imported_db(emoji_fixture: Path):
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
