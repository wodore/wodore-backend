"""Flag Icons source plugin (lipis/flag-icons, MIT).

Layout: flat flag SVGs keyed by ISO 3166 code at ``flags/4x3/<code>.svg``
and ``flags/1x1/<code>.svg``. Flat flags are ``primitive`` style (the
wavy emoji flags of the noto pack are the color-style variant); the two
ratios import as separate icons with distinct slugs — 4:3 as
``flag-switzerland``, the square crop as ``flag-switzerland-square``.
Only codes with a Unicode emoji equivalent are imported (see
``flags.py``) — the repo also carries regional/variant flags
(``es-ct``, ``sh-ac``, …) that have no emoji identity.
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

#: Aspect-ratio directories imported as slug variants — all simple
#: style, the square crop distinguished by slug and name suffix.
FLAG_ICONS_VARIANTS: tuple[tuple[str, str, str], ...] = (
    # (ratio directory, slug suffix, name suffix)
    ("4x3", "", ""),
    ("1x1", "-square", " (square)"),
)


class FlagIconsSource(IconSource):
    """Country flags, rectangular — 4:3 and square variants."""

    spec: ClassVar[SourceSpec] = FLAG_ICONS_SPEC

    def source_dir(self, base_dir: Path) -> Path:
        return base_dir / "flag-icons" / "flags"

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        self.reset()
        for ratio, slug_suffix, name_suffix in FLAG_ICONS_VARIANTS:
            for svg_path in sorted((source_dir / ratio).glob("*.svg")):
                candidate = flag_candidate(
                    svg_path.stem,
                    {"primitive": svg_path},
                    entries,
                    self.unique_slug,
                    slug_suffix=slug_suffix,
                    name_suffix=name_suffix,
                )
                if candidate is not None:
                    yield candidate
