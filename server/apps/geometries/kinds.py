"""Place kinds — seed registry + DB-contract runtime.

OpenSpec ``geoplace-category-tree``: a place's kind is its anchoring
category (first category by ``(order, slug)``); the **contract group**
is that category's parent (``accommodation`` for a hut); the
super-roots (``amenity`` / ``admin`` / ``natural``) sit above the
contract groups under the ``map`` namespace root. The stored
``GeoPlace.kind_slug`` is the super-root's identifier — ``map.amenity``,
``map.admin``, ``map.natural`` — derived on write (consumed by
tile/clustering SQL).

The contract itself lives in the DB (``CategoryKindContract`` on the
contract group — admin-editable, ``CategoryExtraSchema`` parity): the
classifier subtrees allowed on associations and whether
operations/seasonality rows may exist. This module is the **seed
source** for those rows (migrations copy it verbatim) plus the
depth-guarded runtime derivation helpers. Vocabulary roots (mode,
role, relations, external_link, link_type) are excluded from kind
resolution — they classify associations, never places.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Namespace root separating map categories from vocabulary trees.
MAP_ROOT_SLUG: str = "map"

#: Super-roots directly under ``map`` (kind_slug = f"map.{slug}").
SUPER_ROOT_SLUGS: frozenset[str] = frozenset({"amenity", "admin", "natural"})

#: Stored ``GeoPlace.kind_slug`` values (super-root identifiers).
KIND_AMENITY: str = "map.amenity"
KIND_ADMIN: str = "map.admin"
KIND_NATURAL: str = "map.natural"
KIND_NONE: str = "none"

_VALID_KIND_SLUGS: frozenset[str] = frozenset(
    {KIND_AMENITY, KIND_ADMIN, KIND_NATURAL, KIND_NONE}
)


@dataclass(frozen=True)
class PlaceKind:
    """Seed contract for one contract-group category (kinds registry)."""

    #: Super-root slug the group lives under (kind group parent).
    super_root: str
    #: Classifier subtree root slugs allowed on associations under
    #: this group — e.g. ``("mode",)`` for accommodation only.
    classifiers: tuple[str, ...] = field(default_factory=tuple)
    #: Places under this group may carry GeoPlaceOperation rows.
    has_operations: bool = False
    #: Places under this group may carry GeoPlaceSeasonality rows.
    has_seasonality: bool = False

    @property
    def kind_slug(self) -> str:
        """Stored kind_slug — the super-root's identifier."""
        return f"{MAP_ROOT_SLUG}.{self.super_root}"


#: Contract-group slug → seed contract. Pinned against the live
#: category tree (gaps intentionally fall to the empty contract).
PLACE_KINDS: dict[str, PlaceKind] = {
    # accommodation carries operating modes, operations + seasonality
    "accommodation": PlaceKind(
        "amenity", classifiers=("mode",), has_operations=True, has_seasonality=True
    ),
    # amenity-ish groups without classifier contracts yet
    "tourism": PlaceKind("amenity"),
    "sport": PlaceKind("amenity"),
    "shopping": PlaceKind("amenity"),
    "food_supply": PlaceKind("amenity"),
    "restaurant": PlaceKind("amenity"),
    "groceries": PlaceKind("amenity"),
    "services": PlaceKind("amenity"),
    "finance": PlaceKind("amenity"),
    "health_and_emergency": PlaceKind("amenity"),
    "outdoor_services": PlaceKind("amenity"),
    "utilities": PlaceKind("amenity"),
    "automotive": PlaceKind("amenity"),
    "meteo": PlaceKind("amenity"),
    "availability": PlaceKind("amenity"),
    "transport": PlaceKind("amenity"),
    "administrative": PlaceKind("admin"),
    "populated_place": PlaceKind("admin"),
    "terrain": PlaceKind("natural"),
    "hydrographic": PlaceKind("natural"),
}

#: Vocabulary roots never anchor a kind (association classifiers, uri
#: kinds, link trees).
KIND_VOCABULARY_ROOTS: frozenset[str] = frozenset(
    {"mode", "role", "relations", "external_link", "link_type"}
)


def kind_root_category(categories: Any) -> Any:
    """The contract-group category anchoring a place's kind.

    The parent of the first category by ``(order, slug)`` —
    deterministic, the rule ``GeoPlace.__str__`` uses. A root category
    itself anchors directly (vocabulary edge — no contract group).
    """
    ordered = sorted(
        (c for c in categories if c is not None),
        key=lambda c: (c.order, c.slug),
    )
    if not ordered:
        return None
    first = ordered[0]
    return first.parent if first.parent is not None else first


def contract_for_group(group: Any) -> Any:
    """The DB contract for a contract-group category (or ``None``).

    ``None`` is the empty contract — no classifiers, no operations,
    no seasonality. Admin edits apply immediately — no caching.
    """
    if group is None:
        return None
    from .models._kind_contract import CategoryKindContract

    return CategoryKindContract.objects.filter(category=group).first()


def kind_contract_for(category: Any) -> Any:
    """The DB contract for a place's anchoring category.

    Resolves the contract group (the category's parent — the root
    group in the map tree) and returns its ``CategoryKindContract``,
    or ``None`` when the category has no parent or the group carries
    no contract row (empty contract: no classifiers, no operations,
    no seasonality). Admin edits apply immediately — no caching.
    """
    if category is None:
        return None
    parent = getattr(category, "parent", None)
    if parent is None:
        return None
    return contract_for_group(parent)


def place_kind_slug(categories: Any) -> str:
    """Derived ``kind_slug`` for a place's categories (map.<super>).

    Depth-guarded walk: only a kind-level category (parent = contract
    group, grandparent = super-root, great-grandparent = ``map``)
    anchors a kind. Shallower anchors (contract groups, super-roots,
    vocabulary) are skipped — never "map" or a partial path.
    """
    ordered = sorted(
        (c for c in categories if c is not None),
        key=lambda c: (c.order, c.slug),
    )
    for cat in ordered:
        group = getattr(cat, "parent", None)
        super_root = getattr(group, "parent", None) if group is not None else None
        namespace = (
            getattr(super_root, "parent", None) if super_root is not None else None
        )
        if (
            namespace is not None
            and namespace.slug == MAP_ROOT_SLUG
            and super_root is not None
            and super_root.slug in SUPER_ROOT_SLUGS
        ):
            return f"{namespace.slug}.{super_root.slug}"
    return KIND_NONE


def assert_registry_valid() -> None:
    """Registry super-roots ⊆ the seeded super-root set (test-pinned)."""
    invalid = {
        root: kind.super_root
        for root, kind in PLACE_KINDS.items()
        if kind.super_root not in SUPER_ROOT_SLUGS
    }
    if invalid:
        msg = f"PLACE_KINDS super_roots outside the seeded set: {invalid}"
        raise ValueError(msg)
