"""Place kinds — seed registry + DB-contract runtime.

OpenSpec ``geoplace-category-tree``: a place's kind is its anchoring
category (first category by ``(order, slug)``); the **contract group**
is that category's parent (``accommodation`` for a hut); the
super-roots (``amenity`` / ``admin`` / ``natural``) sit above the
contract groups under the ``map`` namespace root. The stored
``GeoPlace.domain`` is the super-root slug — ``amenity``,
``admin``, ``natural`` — derived on write (consumed by
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

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

#: Namespace root separating map categories from vocabulary trees.
MAP_ROOT_SLUG: str = "map"

#: Super-roots directly under ``map`` (domain = the super-root slug).
SUPER_ROOT_SLUGS: frozenset[str] = frozenset({"amenity", "admin", "natural"})

#: Stored ``GeoPlace.domain`` values (super-root identifiers).
DOMAIN_AMENITY: str = "amenity"
DOMAIN_ADMIN: str = "admin"
DOMAIN_NATURAL: str = "natural"
DOMAIN_NONE: str = "none"

_VALID_DOMAIN_SLUGS: frozenset[str] = frozenset(
    {DOMAIN_AMENITY, DOMAIN_ADMIN, DOMAIN_NATURAL, DOMAIN_NONE}
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
    def domain(self) -> str:
        """Stored domain — the super-root slug (plain, no prefix)."""
        return self.super_root


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
DOMAIN_VOCABULARY_ROOTS: frozenset[str] = frozenset(
    {"mode", "role", "relations", "external_link", "link_type"}
)


def anchor_category(categories: Any) -> Any:
    """The anchoring kind category — first by ``(order, slug)``.

    The exact rule ``GeoPlace.__str__`` and the tiles JSON ordering
    use; ``GeoPlace.kind`` stores it (geoplace-kind-fk),
    ``kind_root_category`` resolves its contract group.
    """
    ordered = sorted(
        (c for c in categories if c is not None),
        key=lambda c: (c.order, c.slug),
    )
    return ordered[0] if ordered else None


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


_ContractState = tuple[Any, tuple[str, ...]]
#: group pk → (contract row | None, allowed classifier slugs).
#: Active only inside ``contract_cache()`` — batch imports pay one
#: query per distinct contract group instead of 2-3 per place
#: (admin/API paths stay uncached: admin edits apply immediately).
_contract_cache: contextvars.ContextVar[dict[int, _ContractState] | None] = (
    contextvars.ContextVar("wodore_contract_cache", default=None)
)


@contextmanager
def contract_cache() -> Iterator[None]:
    """Batch-scope kind-contract cache for import loops.

    Wrap an import loop: contract lookups (row + allowed classifiers)
    are fetched once per distinct contract group. Correctness: the
    cache lives only inside the ``with`` block — no admin-edit race
    beyond the batch's own lifetime.
    """
    token = _contract_cache.set({})
    try:
        yield
    finally:
        _contract_cache.reset(token)


def _contract_state_for_group(group: Any) -> _ContractState:
    from .models._kind_contract import CategoryKindContract

    cache = _contract_cache.get()
    key = group.pk
    if cache is not None and key in cache:
        return cache[key]
    contract = CategoryKindContract.objects.filter(category=group).first()
    allowed = (
        tuple(contract.allowed_classifiers.values_list("slug", flat=True))
        if contract is not None
        else ()
    )
    state: _ContractState = (contract, allowed)
    if cache is not None:
        cache[key] = state
    return state


def contract_for_group(group: Any) -> Any:
    """The DB contract for a contract-group category (or ``None``).

    ``None`` is the empty contract — no classifiers, no operations,
    no seasonality. Admin edits apply immediately — no process-level
    caching (a batch-scope cache may serve imports, see
    ``contract_cache()``).
    """
    if group is None:
        return None
    return _contract_state_for_group(group)[0]


def kind_contract_state(category: Any) -> _ContractState:
    """(contract | None, allowed classifier slugs) for a kind category.

    Single round-trip per group (cached under ``contract_cache()``) —
    ``validate_attributes`` needs both parts and must not pay one
    query each.
    """
    if category is None:
        return None, ()
    parent = getattr(category, "parent", None)
    if parent is None:
        return None, ()
    return _contract_state_for_group(parent)


def kind_contract_for(category: Any) -> Any:
    """The DB contract for a place's anchoring category.

    Resolves the contract group (the category's parent — the root
    group in the map tree) and returns its ``CategoryKindContract``,
    or ``None`` when the category has no parent or the group carries
    no contract row (empty contract: no classifiers, no operations,
    no seasonality).
    """
    return kind_contract_state(category)[0]


def place_domain(categories: Any) -> str:
    """Derived ``domain`` for a place's categories (super-root slug).

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
            return super_root.slug
    return DOMAIN_NONE


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
