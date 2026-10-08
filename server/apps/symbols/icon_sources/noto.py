"""Noto Emoji source plugin (googlefonts/noto-emoji, Apache-2.0).

Layout: color SVGs at ``2D/svg/emoji_u<codepoints>.svg`` (codepoints
``_``-joined lowercase hex, no variation selectors). One style only:
color → detailed. Slugs join on the hexcode; files without an
emojibase match keep a filename-derived slug without keywords.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from server.apps.symbols.icon_data import normalize_hexcode
from server.apps.symbols.icon_sources.base import (
    IconCandidate,
    IconSource,
    SourceSpec,
    slugify,
)

NOTO_SPEC = SourceSpec(
    key="noto",
    pack_slug="noto-emoji",
    org_slug="google",
    org_name="Google",
    license={
        "slug": "apache-2-0",
        "name": "Apache-2.0",
        "fullname": "Apache License 2.0",
        "url": "https://github.com/googlefonts/noto-emoji/blob/main/fonts/LICENSE",
    },
    repo_url="https://github.com/googlefonts/noto-emoji/archive/{ref}.tar.gz",
    web_url="https://github.com/googlefonts/noto-emoji/tree/{ref}",
    extract_marker="2D",
)


class NotoSource(IconSource):
    """The complete Noto Emoji color set (secondary emoji pack)."""

    spec: ClassVar[SourceSpec] = NOTO_SPEC

    def source_dir(self, base_dir: Path) -> Path:
        return base_dir / "noto" / "2D" / "svg"

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        self.reset()
        for svg_path in sorted(source_dir.glob("emoji_u*.svg")):
            codepoints = svg_path.stem[len("emoji_u") :].split("_")
            hexcode = normalize_hexcode("-".join(codepoints))
            entry = entries.get(hexcode)
            if entry is not None:
                slug = self.unique_slug(entry["slug"])
            else:
                # Slugify: raw stems contain underscores (codepoints are
                # `_`-joined) — icon slugs are kebab-case everywhere.
                slug = self.unique_slug(
                    slugify(svg_path.stem.replace("emoji_u", "emoji-", 1))
                )
            yield IconCandidate(
                slug=slug,
                fallback_name=svg_path.stem,
                hexcode=hexcode,
                styles={"detailed": svg_path},
                entry=entry,
            )
