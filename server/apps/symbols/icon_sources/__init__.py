"""Source plugins for the icon import (openspec: icon-library).

Each upstream icon source plugs in as an ``IconSource`` subclass: it
declares its pack/org/license metadata (``SourceSpec``) and knows how
to walk its downloaded tree into ``IconCandidate`` rows. Everything
else — Symbol/Icon/IconKeyword upserts, taxonomy, curated shortlist —
is handled generically by the ``icon_import`` command.

Adding a source: new module here + register it in ``SOURCES``. No
schema, API, or command changes.
"""

from .base import IconCandidate, IconSource, SourceSpec
from .fluent import FluentSource
from .noto import NotoSource

SOURCES: dict[str, IconSource] = {
    source.spec.key: source for source in (FluentSource(), NotoSource())
}

__all__ = [
    "SOURCES",
    "FluentSource",
    "IconCandidate",
    "IconSource",
    "NotoSource",
    "SourceSpec",
]
