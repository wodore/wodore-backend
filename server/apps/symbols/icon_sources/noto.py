"""Noto Emoji source plugin (googlefonts/noto-emoji, Apache-2.0).

Layout: color SVGs at ``2D/svg/emoji_u<codepoints>.svg`` (codepoints
``_``-joined lowercase hex, no variation selectors). One style only:
color → color-style. Slugs join on the hexcode; files without an
emojibase match keep a filename-derived slug without keywords.

Country flags ship outside that set, under
``third_party/region-flags/waved-svg`` (public domain): the waved
SVGs are the emoji-flag artwork of ``NotoColorEmoji-flagsonly.ttf``,
named exactly like the 2D set (``emoji_u1f1e8_1f1ed.svg``) — same
parse, same emojibase join, also imported as color style. The flat
ISO-code ``svg/`` set next to it covers the flat-rectangular ground
already served by the ``flag-icons`` pack and is not imported.
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
            yield self._candidate(svg_path, entries)
        # ``<base>/noto/2D/svg`` → ``<base>/noto`` → region flags.
        flags_dir = source_dir.parents[1] / "third_party" / "region-flags" / "waved-svg"
        if flags_dir.is_dir():
            for svg_path in sorted(flags_dir.glob("emoji_u*.svg")):
                yield self._candidate(svg_path, entries)

    def _candidate(self, svg_path: Path, entries: dict[str, dict]) -> IconCandidate:
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
        return IconCandidate(
            slug=slug,
            fallback_name=svg_path.stem,
            hexcode=hexcode,
            styles={"color": svg_path},
            entry=entry,
        )
