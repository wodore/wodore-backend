"""Shared helpers for the flag icon sources.

Country flags are the one emoji family that ships in neither of the
big emoji packs: Microsoft's Fluent Emoji omits them entirely, and
googlefonts/noto-emoji keeps them out of ``2D/svg`` (the flag assets
live under ``third_party/region-flags``; the font builds even come in
``-noflags``/``-flagsonly`` variants). The flag sources close that gap:
their SVGs are keyed by ISO 3166 code, are mapped onto the Unicode
emoji flag sequences here, and join against emojibase like any emoji
pack — keywords, taxonomy and clean slugs (``flag-switzerland``) come
along for free.

The emojibase join doubles as the whitelist: only assets mapping to a
real Unicode emoji flag (~260 country flags plus England/Scotland/
Wales) are imported. Subdivision/variant assets without an emoji
equivalent (``es-ct``, ``us-*`` states, ``language/*`` …) are skipped.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from server.apps.symbols.icon_sources.base import IconCandidate

_REGIONAL_INDICATOR_A = 0x1F1E6
_LOWER_A = ord("a")
_TAG_BASE = 0xE0000
_CANCEL_TAG = "E007F"
_BLACK_FLAG = "1F3F4"

_CODE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")


def flag_hexcode(code: str) -> str | None:
    """Map an ISO 3166 flag code to its Unicode emoji hexcode.

    ``"ch"`` → ``"1F1E8-1F1ED"`` (regional-indicator pair);
    ``"gb-eng"`` → ``"1F3F4-E0067-…-E007F"`` (flag tag sequence).
    Returns ``None`` for codes that cannot map (underscores, multi-dash
    variants like ``us-betsy_ross``, …).
    """
    code = code.lower()
    if _CODE.fullmatch(code) is None:
        return None
    country, dash, subdivision = code.partition("-")
    if dash:
        tags = "-".join(
            f"{_TAG_BASE + ord(char):X}" for char in f"{country}{subdivision}"
        )
        return f"{_BLACK_FLAG}-{tags}-{_CANCEL_TAG}"
    return "-".join(
        f"{_REGIONAL_INDICATOR_A + ord(char) - _LOWER_A:X}" for char in country
    )


def flag_candidate(
    code: str,
    styles: dict[str, Path],
    entries: dict[str, Any],
    unique_slug: Callable[[str], str],
    slug_suffix: str = "",
    name_suffix: str = "",
) -> IconCandidate | None:
    """Build the emojibase-joined candidate for one flag code.

    ``slug_suffix``/``name_suffix`` distinguish same-flag variants
    imported as separate icons (e.g. flag-icons' square crop).
    Returns ``None`` when the code has no Unicode emoji equivalent —
    flag sources import only the emoji set (the join is the whitelist,
    see module docstring).
    """
    hexcode = flag_hexcode(code)
    entry = entries.get(hexcode) if hexcode else None
    if entry is None:
        return None
    if name_suffix:
        # The import names icons from the entry, not the fallback —
        # decorate it so the variant label reaches ``Icon.name``.
        entry = {**entry, "name": f"{entry['name']}{name_suffix}"}
    return IconCandidate(
        slug=unique_slug(f"{entry['slug']}{slug_suffix}"),
        fallback_name=entry["name"],
        hexcode=hexcode,
        styles=styles,
        entry=entry,
    )
