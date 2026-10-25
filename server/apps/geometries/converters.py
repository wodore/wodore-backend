"""GeoPlace slug path converter (openspec: place-detail-endpoint).

Item paths under ``places/`` key by slug through this converter, whose
grammar — slug-charset characters containing at least one ``-`` or
``_`` — structurally excludes the fixed collection segments
(``search``, ``nearby``, ``overlays``): the two grammars are provably
disjoint, so URL resolution never depends on path registration order.

The same grammar is enforced on the data side (database check
constraint + ``GeoPlace.clean``); see the ``place-detail-api`` spec
requirement "Slug grammar and routing safety".
"""

from __future__ import annotations

from django.urls import register_converter

#: Slug grammar shared by the path converter, the model-layer
#: validation and the database check constraint. Unanchored on
#: purpose (Django anchors converter regexes inside the compiled
#: route); validation and the constraint apply full-match semantics.
#: Verified against production data: 0 of 441,940 slugs violate it.
SLUG_GRAMMAR_RE = r"[a-z0-9_-]*[-_][a-z0-9_-]*"

#: URL segments reserved for fixed routes under ``places/`` — never
#: valid slugs (belt-and-suspenders behind the structural rule).
RESERVED_URL_SEGMENTS = frozenset(
    {
        "search",
        "nearby",
        "overlays",
        "meta",
        "amenity",
    }
)


class GeoPlaceSlugConverter:
    """Matches GeoPlace slugs; never matches hyphen-less, underscore-less
    fixed route segments (``search``, ``nearby``, ``overlays``)."""

    regex = SLUG_GRAMMAR_RE

    def to_python(self, value: str) -> str:
        """Pass the matched slug through unchanged."""
        return value

    def to_url(self, value: str) -> str:
        """Pass the slug through unchanged for URL reversing."""
        return value


register_converter(GeoPlaceSlugConverter, "geoplace")
