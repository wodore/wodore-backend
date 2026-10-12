"""Flag Icons source plugin (lipis/flag-icons, MIT).

Layout: flat flag SVGs keyed by ISO 3166 code at ``flags/4x3/<code>.svg``
and ``flags/1x1/<code>.svg``. Ratios map to ``Symbol`` styles: 4x3 →
detailed, 1x1 → simple. Only codes with a Unicode emoji equivalent are
imported (see ``flags.py``) — the repo also carries regional/variant
flags (``es-ct``, ``sh-ac``, …) that have no emoji identity.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from server.apps.symbols.icon_sources.base import (
    IconCandidate,
    IconSource,
    SourceSpec,
)
from server.apps.symbols.icon_sources.flags import flag_candidate

FLAG_ICONS_SPEC = SourceSpec(
    key="flag-icons",
    pack_slug="flag-icons",
    org_slug="lipis",
    org_name="Panayiotis Lipiridis",
    license={
        "slug": "mit",
        "name": "MIT",
        "fullname": "MIT License",
        "url": "https://github.com/lipis/flag-icons/blob/main/LICENSE",
    },
    repo_url="https://github.com/lipis/flag-icons/archive/{ref}.tar.gz",
    web_url="https://github.com/lipis/flag-icons/tree/{ref}",
    extract_marker="flags",
)

#: Subdirectories (aspect ratios) mapped to ``Symbol`` styles.
FLAG_ICONS_STYLES: tuple[tuple[str, str], ...] = (
    ("4x3", "detailed"),
    ("1x1", "simple"),
)


class FlagIconsSource(IconSource):
    """Country flags, rectangular — 4:3 and 1:1 ratios."""

    spec: ClassVar[SourceSpec] = FLAG_ICONS_SPEC

    def source_dir(self, base_dir: Path) -> Path:
        return base_dir / "flag-icons" / "flags"

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        self.reset()
        # Both ratios describe the same flag: merge into one candidate
        # carrying two styles (the icon upsert is idempotent either way).
        styles_by_code: dict[str, dict[str, Path]] = {}
        for ratio, style in FLAG_ICONS_STYLES:
            for svg_path in sorted((source_dir / ratio).glob("*.svg")):
                styles_by_code.setdefault(svg_path.stem, {})[style] = svg_path
        for code in sorted(styles_by_code):
            candidate = flag_candidate(
                code, styles_by_code[code], entries, self.unique_slug
            )
            if candidate is not None:
                yield candidate
