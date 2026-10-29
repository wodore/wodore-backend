"""Place kinds — the category-taxonomy contract registry.

OpenSpec ``geoplace-kinds-operations-graph``: a place's kind is its
anchoring category (the parent of the first category by
``(order, slug)`` — the rule ``GeoPlace.__str__`` already uses); the
root parents double as overlay groups. This registry (code, not DB —
structure belongs in git, data schemas in ``CategoryExtraSchema``)
maps each root parent to its contract: the stored-but-derived
``detail_type`` (consumed by tile/clustering SQL) and the classifier
subtrees allowed on associations under that parent.

Registry values are asserted ⊆ the ``GeoPlace.detail_type`` check
constraint (amenity/transport/admin/natural/none). Vocabulary roots
(mode, role, relations, external_link, link_type) are excluded from
kind resolution — they classify associations, never places.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlaceKind:
    """Contract for one category-root group of places."""

    #: Stored ``GeoPlace.detail_type`` (derived on write)
    detail_type: str
    #: Classifier subtrees (root parent slugs) allowed on associations
    #: under this kind — e.g. ``("mode",)`` for accommodation only.
    classifiers: tuple[str, ...] = field(default_factory=tuple)


_AMENITY = PlaceKind("amenity")
_AMENITY_WITH_MODE = PlaceKind("amenity", classifiers=("mode",))

#: Root-parent slug → contract. Pinned against the live category tree
#: (openspec geoplace-kinds: gaps intentionally fall to the default).
PLACE_KINDS: dict[str, PlaceKind] = {
    # accommodation carries operating modes; everything amenity-ish else
    # has no classifier contracts yet
    "accommodation": _AMENITY_WITH_MODE,
    "tourism": _AMENITY,
    "sport": _AMENITY,
    "shopping": _AMENITY,
    "food_supply": _AMENITY,
    "restaurant": _AMENITY,
    "groceries": _AMENITY,
    "services": _AMENITY,
    "finance": _AMENITY,
    "health_and_emergency": _AMENITY,
    "outdoor_services": _AMENITY,
    "utilities": _AMENITY,
    "automotive": _AMENITY,
    "meteo": _AMENITY,
    "availability": _AMENITY,
    "transport": PlaceKind("transport"),
    "administrative": PlaceKind("admin"),
    "populated_place": PlaceKind("admin"),
    "terrain": PlaceKind("natural"),
    "hydrographic": PlaceKind("natural"),
}

#: Vocabulary roots never anchor a kind (association classifiers, uri
#: kinds, link trees) — a place mis-anchored to one falls to DEFAULT.
KIND_VOCABULARY_ROOTS: frozenset[str] = frozenset(
    {"mode", "role", "relations", "external_link", "link_type"}
)

#: Fallback for unmapped and vocabulary roots.
DEFAULT_KIND: PlaceKind = _AMENITY

#: Detail types the GeoPlace check constraint permits — the registry
#: asserts its values against this (test-pinned).
#: GeoPlace.detail_type check-constraint values (GeoPlace._ReviewStatusChoices
# -style TextChoices; literals avoid a circular models import).
_DETAIL_TYPES: frozenset[str] = frozenset(
    {"amenity", "transport", "admin", "natural", "none"}
)


def kind_for_root(root_slug: str | None) -> PlaceKind:
    """Contract for a category root parent slug."""
    if root_slug is None or root_slug in KIND_VOCABULARY_ROOTS:
        return DEFAULT_KIND
    return PLACE_KINDS.get(root_slug, DEFAULT_KIND)


def kind_for(category: Any) -> PlaceKind:
    """Contract for a place's anchoring category.

    Resolves through the category's parent (the root group); a root
    category itself anchors directly.
    """
    if category is None:
        return DEFAULT_KIND
    parent = getattr(category, "parent", None)
    root_slug = parent.slug if parent is not None else getattr(category, "slug", None)
    return kind_for_root(root_slug)


def kind_root_category(categories: Any) -> Any:
    """The root category anchoring a place's kind.

    The parent of the first category by ``(order, slug)`` —
    deterministic, the rule ``GeoPlace.__str__`` uses. Root categories
    anchor directly.
    """
    ordered = sorted(
        (c for c in categories if c is not None),
        key=lambda c: (c.order, c.slug),
    )
    if not ordered:
        return None
    first = ordered[0]
    return first.parent if first.parent is not None else first


def place_detail_type(categories: Any) -> str:
    """Derived ``detail_type`` for a place's categories."""
    root = kind_root_category(categories)
    if root is None:
        return "none"
    return kind_for(root).detail_type


def assert_registry_valid() -> None:
    """Registry values ⊆ the detail_type check-constraint set
    (asserted at import by tests: test asserts PLACE_KINDS values ⊆
    the GeoPlace detail_type constraint)."""
    invalid = {
        root: kind.detail_type
        for root, kind in PLACE_KINDS.items()
        if kind.detail_type not in _DETAIL_TYPES
    }
    if invalid:
        msg = f"PLACE_KINDS detail_type values outside the DB constraint: {invalid}"
        raise ValueError(msg)
