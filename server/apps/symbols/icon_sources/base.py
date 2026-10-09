"""Icon source plugin contract (openspec: icon-library)."""

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


def slugify(value: str) -> str:
    """Standalone slugify mirroring Django's (usable from plugins)."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = "".join(c if c.isalnum() else "-" for c in value.lower())
    return re.sub(r"-+", "-", value).strip("-")


@dataclass(frozen=True)
class SourceSpec:
    """Static metadata of one upstream icon source.

    ``key`` selects the source on the command line
    (``icon_import --source <key>``); the pack row is
    ``pack_slug``. ``repo_url`` is the tarball template, ``web_url``
    the human-readable tree URL (recorded on ``Symbol.source_url``).
    """

    key: str
    pack_slug: str
    org_slug: str
    org_name: str
    license: dict  # {"slug", "name", "fullname", "url"}
    repo_url: str  # tarball template with {ref}
    web_url: str  # browsable tree template with {ref}
    extract_marker: str  # top-level dir that must exist post-extraction
    needs_emojibase: bool = True


@dataclass
class IconCandidate:
    """One upstream icon walked out of a source tree.

    ``slug`` is the clean pack-unique icon slug, ``hexcode`` the
    optional unicode (None for non-emoji assets — the field is
    optional enrichment, identity is the slug). ``styles`` maps
    ``Symbol`` styles to downloaded SVG paths; ``entry`` is the
    emojibase match (None when unmatched: no keywords/taxonomy).
    """

    slug: str
    fallback_name: str
    hexcode: str | None
    styles: dict[str, Path] = field(default_factory=dict)
    entry: dict | None = None


class IconSource:
    """Base class: walks a downloaded source tree into candidates."""

    spec: ClassVar[SourceSpec]

    def __init__(self) -> None:
        self._used_slugs: set[str] = set()

    def reset(self) -> None:
        """Start a fresh run (slug-uniqueness state)."""
        self._used_slugs = set()

    def source_dir(self, base_dir: Path) -> Path:
        """Location of this source's tree inside the data root."""
        raise NotImplementedError

    def iter_candidates(
        self, source_dir: Path, entries: dict[str, dict]
    ) -> Iterator[IconCandidate]:
        """Yield one candidate per upstream icon.

        ``entries`` are the parsed emojibase entries keyed by
        normalized hexcode (empty for non-emoji sources).
        """
        raise NotImplementedError

    def unique_slug(self, slug: str) -> str:
        """Guarantee slug uniqueness within an import run."""
        candidate = slug
        counter = 2
        while candidate in self._used_slugs:
            candidate = f"{slug}-{counter}"
            counter += 1
        self._used_slugs.add(candidate)
        return candidate
