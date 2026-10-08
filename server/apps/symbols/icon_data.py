"""Shared data helpers for the icon library (openspec: icon-library).

Constants and pure functions used by both the emoji import command and
the curated-shortlist data migration. Kept free of Django imports so
data migrations can import it safely.
"""

from __future__ import annotations

import re
import unicodedata

#: emojibase-data npm package version pinned for imports (MIT).
#: Keywords and CLDR taxonomy names are sourced from it (design D5).
EMOJIBASE_VERSION = "7.0.1"

#: Default locales for keyword import — the four UI languages.
DEFAULT_LOCALES = ("de", "en", "fr", "it")

#: Upstream Fluent Emoji styles mapped to ``Symbol`` styles (design D1).
FLUENT_STYLES: tuple[tuple[str, str], ...] = (
    ("Color", "detailed"),
    ("Flat", "simple"),
    ("High Contrast", "mono"),
)

#: The ~18-icon activity shortlist shown by the picker before any query.
#: Slugs are the import-generated slugs (slugified English CLDR labels)
#: in the ``fluent-emoji`` pack; the same slugs exist in ``noto-emoji``
#: where available, but curation is keyed on the primary pack.
CURATED_ACTIVITY_SLUGS: tuple[str, ...] = (
    "bicycle",
    "camping",
    "canoe",
    "compass",
    "fire",
    "hiking-boot",
    "hot-springs",
    "ice-skate",
    "national-park",
    "parachute",
    "person-climbing",
    "person-mountain-biking",
    "person-swimming",
    "sailboat",
    "skier",
    "snow-capped-mountain",
    "snowboarder",
    "snowflake",
    "sun",
    "tent",
)

_FE0F = "FE0F"
_HEXSEP = re.compile(r"[-_\s]+")
_WS = re.compile(r"\s+")


def normalize_hexcode(raw: str) -> str:
    """Normalize a unicode hexcode for joins (design D5).

    Uppercases, splits on ``-``/``_``/whitespace and strips variation
    selector-16 (FE0F): ``"26fa"``, ``"2764-FE0F"`` and ``"1f469_200d_2764"``
    normalize to ``"26FA"``, ``"2764"`` and ``"1F469-200D-2764"``.
    """
    parts = [part for part in _HEXSEP.split(raw.strip().upper()) if part]
    return "-".join(part for part in parts if part != _FE0F)


def fold_keyword(text: str) -> str:
    """Fold a keyword for matching: strip accents and case.

    ``"Randonnée"`` → ``"randonnee"``, ``"Zelt"`` → ``"zelt"``. The
    original form is retained on ``IconKeyword.keyword`` (design D5).
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WS.sub(" ", stripped).strip().casefold()
