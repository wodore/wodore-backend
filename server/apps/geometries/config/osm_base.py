"""Base classes for OSM category mappings."""

from dataclasses import dataclass, field
from typing import Callable, Optional, Union


@dataclass
class OSMMapping:
    """
    Declarative OSM tag to category mapping with flexible filter support.

    osm_filters is always a list where:
    - List items are AND-ed together
    - Tuple items within the list are OR-ed together
    - str items are single tag checks
    - Filter instances are custom osmium filters

    Examples:
        # Simple mapping - single tag
        OSMMapping(
            osm_filters=["shop=bakery"],
            category_slug="groceries.bakery",
        )

        # OR mapping - multiple options
        OSMMapping(
            osm_filters=[("shop=convenience", "shop=general")],
            category_slug="groceries.convenience",
        )

        # AND mapping - must have both
        OSMMapping(
            osm_filters=["amenity=cafe", "cuisine=coffee"],
            category_slug="restaurant.coffee_shop",
        )

        # Complex - AND + OR
        OSMMapping(
            osm_filters=[
                ("shop=bakery", "craft=bakery"),  # Must be one of these (OR)
                "organic=yes",                     # AND must have this
            ],
            category_slug="groceries.organic_bakery",
        )

        # Key-only filter (checks if key exists)
        OSMMapping(
            osm_filters=["website"],
            category_slug="poi.with_website",
        )

        # With condition for complex Python logic
        OSMMapping(
            osm_filters=["amenity=vending_machine"],
            category_slug="groceries.vending_machine",
            condition=lambda tags: tags.get('vending') in ['food', 'drinks'],
        )

        # With multilingual default name for unnamed places
        OSMMapping(
            osm_filters=["amenity=bank"],
            category_slug="finance.bank",
            mapcomplete_theme="banks",
            priority=0,
            default_name={"en": "Bank", "de": "Bank", "fr": "Banque", "it": "Banca"},
        )

        # With importance range for dynamic calculation
        OSMMapping(
            osm_filters=["shop=bakery"],
            category_slug="groceries.bakery",
            importance_range=(30, 50, 70),  # (min, base, max)
        )
    """

    osm_filters: list[Union[str, tuple[str, ...]]]
    """
    List of filters (AND logic):
    - str: Single tag "shop=bakery" or key "shop"
    - tuple: OR of tags ("shop=bakery", "shop=convenience")
    """

    category_slug: str
    """Target category slug (e.g., 'groceries.bakery')"""

    condition: Optional[Callable[[dict], bool]] = None
    """Optional filter function to check additional tag conditions"""

    pre_process: Optional[Callable[[dict], dict]] = None
    """Optional function to transform tags before mapping (returns modified tags dict)"""

    post_process: Optional[Callable[[dict, dict], dict]] = None
    """Optional function to add extra data after mapping (receives tags and extracted data, returns modified data dict)"""

    mapcomplete_theme: str = "shops"
    """MapComplete theme for OSM edit links"""

    priority: int = 0
    """Priority for this mapping (lower number = higher priority, used when multiple mappings match)"""

    default_name: Optional[dict] = field(default_factory=dict)
    """
    Optional multilingual default name for unnamed places.

    Dictionary with language codes as keys and translated names as values.
    Example: {"en": "Bank", "de": "Bank", "fr": "Banque", "it": "Banca"}

    If empty (default), no default name will be added - only use OSM name/brand/operator tags.
    This prevents adding names to places that genuinely shouldn't have them.
    """

    importance_range: Optional[tuple[int, int, int]] = None
    """
    Optional importance range for OSM-imported places (min, base, max).

    Used by the import script to calculate dynamic importance based on OSM tags.
    The final importance is calculated as:
    - Start with base value
    - Add points for: name presence, tag completeness, brand, wikipedia
    - Clamp to [min, max] range

    Example: (30, 50, 70) means:
    - Minimum: 30 (unnamed, no extra tags)
    - Base: 50 (named place with basic info)
    - Maximum: 70 (named, full tags, brand, wikipedia)

    If not set, uses default importance (25).
    """


@dataclass
class CategoryMappings:
    """
    Collection of OSM mappings for a single category.

    Example:
        GROCERIES = CategoryMappings(
            category="groceries",
            mappings=[
                OSMMapping(osm_filters=["shop=supermarket"], category_slug="groceries.supermarket"),
                OSMMapping(osm_filters=["shop=bakery"], category_slug="groceries.bakery"),
            ],
            detail_type="amenity",
        )
    """

    category: str
    """Top-level category name (e.g., 'groceries', 'restaurant')"""

    mappings: list[OSMMapping]
    """List of OSM tag mappings for this category"""

    detail_type: str = "amenity"
    """GeoPlace detail_type (amenity, transport, admin, natural, accommodation)"""

    enabled: bool = True
    """Whether this category is enabled for import"""

    def get_osm_filters(self) -> list:
        """Get all OSM filters for osmium filtering."""
        filters = []
        for mapping in self.mappings:
            filters.extend(mapping.osm_filters)
        return filters

    def match_category(self, tags: dict) -> Optional[tuple[str, OSMMapping]]:
        """
        Find matching category slug for given OSM tags.

        Returns:
            Tuple of (category_slug, mapping) if match found, None otherwise.
            If multiple mappings match, returns the one with lowest priority number.
        """
        matches = []

        for mapping in self.mappings:
            if self._tags_match(tags, mapping.osm_filters):
                if mapping.condition is None or mapping.condition(tags):
                    matches.append((mapping.category_slug, mapping))

        if not matches:
            return None

        # Sort by priority (lower number = higher priority)
        matches.sort(key=lambda m: m[1].priority)
        return matches[0]

    def _tags_match(self, tags: dict, osm_filters: list) -> bool:
        """
        Check if tags match osm_filters (AND logic with OR support).

        Args:
            tags: Dictionary of OSM tags
            osm_filters: List of filters (str, tuple, or Filter)

        Returns:
            True if all filters match (AND), False otherwise
        """
        for item in osm_filters:
            if isinstance(item, tuple):
                # Tuple = OR: at least one must match
                if not any(self._matches_single_tag(tags, t) for t in item):
                    return False  # None matched, fail AND

            elif isinstance(item, str):
                # Single tag must match
                if not self._matches_single_tag(tags, item):
                    return False

            # Note: Filter instances can't be checked here
            # They're only used for pyosmium file filtering
            # If you need complex logic, use condition function

        return True  # All AND conditions passed

    def _matches_single_tag(self, tags: dict, tag_str: str) -> bool:
        """
        Check if single tag pattern matches.

        Args:
            tags: Dictionary of OSM tags
            tag_str: Tag pattern like "shop=bakery" or "shop"

        Returns:
            True if tag matches, False otherwise
        """
        if "=" in tag_str:
            # "shop=bakery" - check key and value
            key, value = tag_str.split("=", 1)
            return tags.get(key) == value
        else:
            # "shop" - check if key exists
            return tag_str in tags
