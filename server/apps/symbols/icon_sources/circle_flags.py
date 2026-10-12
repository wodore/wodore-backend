"""Circle Flags source plugin (HatScripts/circle-flags, MIT).

Layout: round flag SVGs keyed by ISO 3166 code at ``flags/<code>.svg``
(the ``gh-pages`` branch is the code branch — pin it as the ref).
One style only: round → detailed. As with flag-icons, only codes with
a Unicode emoji equivalent are imported (see ``flags.py``); the repo
also carries subdivisions, historical variants and language flags.
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

CIRCLE_FLAGS_SPEC = SourceSpec(
    key="circle-flags",
    pack_slug="circle-flags",
    org_slug="hatscripts",
    org_name="HatScripts",
    license={
        "slug": "mit",
        "name": "MIT",
        "fullname": "MIT License",
        "url": "https://github.com/HatScripts/circle-flags/blob/gh-pages/LICENSE.md",
    },
    repo_url="https://github.com/HatScripts/circle-flags/archive/{ref}.tar.gz",
    web_url="https://github.com/HatScripts/circle-flags/tree/{ref}",
    extract_marker="flags",
)


class CircleFlagsSource(IconSource):
    """Country flags, round — single style."""

    spec: ClassVar[SourceSpec] = CIRCLE_FLAGS_SPEC

    def source_dir(self, base_dir: Path) -> Path:
        return base_dir / "circle-flags" / "flags"

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        self.reset()
        # Non-recursive: ``language/`` and other subdirectories exist
        # next to the country flags and are not emoji-keyed.
        for svg_path in sorted(source_dir.glob("*.svg")):
            candidate = flag_candidate(
                svg_path.stem, {"detailed": svg_path}, entries, self.unique_slug
            )
            if candidate is not None:
                yield candidate
