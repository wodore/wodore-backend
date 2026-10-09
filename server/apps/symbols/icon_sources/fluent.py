"""Fluent Emoji source plugin (microsoft/fluentui-emoji, MIT).

Layout: ``assets/<Name>/{Color,Flat,High Contrast}/*.svg`` or the
skin-tone variant ``assets/<Name>/Default/<Style>/*.svg``, with a
``metadata.json`` per folder carrying the unicode hexcode and CLDR
slug. Styles map Color→detailed, Flat→simple, High Contrast→mono.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from server.apps.symbols.icon_data import FLUENT_STYLES, normalize_hexcode
from server.apps.symbols.icon_sources.base import (
    IconCandidate,
    IconSource,
    SourceSpec,
    slugify,
)

FLUENT_SPEC = SourceSpec(
    key="fluent",
    pack_slug="fluent-emoji",
    org_slug="microsoft",
    org_name="Microsoft",
    license={
        "slug": "mit",
        "name": "MIT",
        "fullname": "MIT License",
        "url": "https://github.com/microsoft/fluentui-emoji/blob/main/LICENSE",
    },
    repo_url="https://github.com/microsoft/fluentui-emoji/archive/{ref}.tar.gz",
    web_url="https://github.com/microsoft/fluentui-emoji/tree/{ref}",
    extract_marker="assets",
)


def _read_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class FluentSource(IconSource):
    """The complete Fluent Emoji set (primary emoji pack)."""

    spec: ClassVar[SourceSpec] = FLUENT_SPEC

    def source_dir(self, base_dir: Path) -> Path:
        return base_dir / "fluent" / "assets"

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        self.reset()
        for folder in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            metadata_path = folder / "metadata.json"
            metadata = _read_json(metadata_path) if metadata_path.exists() else {}
            hexcode = (
                normalize_hexcode(metadata["unicode"])
                if metadata.get("unicode")
                else None
            )
            entry = entries.get(hexcode) if hexcode else None
            if entry is not None:
                slug = self.unique_slug(entry["slug"])
            else:
                slug = self.unique_slug(
                    slugify(metadata.get("cldr") or metadata.get("tts") or folder.name)
                )
            styles: dict[str, Path] = {}
            for style_dir_name, symbol_style in FLUENT_STYLES:
                svg_path = self._find_svg(folder, style_dir_name)
                if svg_path is not None:
                    styles[symbol_style] = svg_path
            yield IconCandidate(
                slug=slug,
                fallback_name=metadata.get("tts") or folder.name,
                hexcode=hexcode,
                styles=styles,
                entry=entry,
            )

    @staticmethod
    def _find_svg(folder: Path, style_dir_name: str) -> Path | None:
        """Locate a style SVG, preferring the Default skin tone.

        Layouts: ``<folder>/<style>/*.svg`` or
        ``<folder>/Default/<style>/*.svg`` (skin-tone families).
        """
        for candidate in (
            folder / style_dir_name,
            folder / "Default" / style_dir_name,
        ):
            if candidate.is_dir():
                svgs = sorted(candidate.glob("*.svg"))
                if svgs:
                    return svgs[0]
        return None
