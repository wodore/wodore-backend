"""
OSM category mappings registry.

Categories are listed in priority order - when multiple categories match the same OSM element,
the first matching category wins.

Usage:
    # Get all enabled categories
    enabled = get_enabled_categories()

    # Get specific categories
    phase1 = get_categories(['groceries', 'restaurant', 'health_and_emergency'])

    # Get all OSM filters for osmium
    filters = get_osm_filters(['groceries', 'restaurant'])
"""

from .osm_automotive import AUTOMOTIVE
from .osm_finance import FINANCE
from .osm_groceries import GROCERIES
from .osm_health_and_emergency import HEALTH_AND_EMERGENCY
from .osm_outdoor_services import OUTDOOR_SERVICES
from .osm_restaurant import RESTAURANT
from .osm_services import SERVICES
from .osm_shopping import SHOPPING
from .osm_sport import SPORT
from .osm_tourism import TOURISM
from .osm_transport import TRANSPORT
from .osm_utilities import UTILITIES

# Category registry in priority order (first = highest priority)
# When multiple categories match the same OSM element, the first match wins
CATEGORY_REGISTRY = [
    # Phase 1: Alpine/tourism core (enabled by default)
    GROCERIES,
    RESTAURANT,
    HEALTH_AND_EMERGENCY,
    TRANSPORT,
    OUTDOOR_SERVICES,
    TOURISM,
    # Phase 2: Supporting services (disabled by default)
    AUTOMOTIVE,
    SPORT,
    UTILITIES,
    FINANCE,
    # Phase 3: General amenities (disabled by default)
    SHOPPING,
    SERVICES,
]


def get_enabled_categories():
    """Get all enabled categories in priority order."""
    return [cat for cat in CATEGORY_REGISTRY if cat.enabled]


def get_categories(category_names: list[str]):
    """
    Get specific categories by name in priority order.

    Args:
        category_names: List of category names (e.g., ['groceries', 'restaurant'])

    Returns:
        List of CategoryMappings in priority order

    Raises:
        ValueError: If any category name is not found
    """
    category_map = {cat.category: cat for cat in CATEGORY_REGISTRY}

    result = []
    for name in category_names:
        if name not in category_map:
            available = ", ".join(category_map.keys())
            raise ValueError(f"Category '{name}' not found. Available: {available}")
        result.append(category_map[name])

    return result


def get_all_categories():
    """Get all categories regardless of enabled status."""
    return CATEGORY_REGISTRY


def get_osm_filters(category_names: list[str]) -> list[str]:
    """
    Get all OSM tag filters for given categories.

    Args:
        category_names: List of category names

    Returns:
        List of OSM tag patterns for osmium filtering (e.g., ['shop=bakery', 'amenity=restaurant'])
    """
    categories = get_categories(category_names)
    filters = []
    for cat in categories:
        filters.extend(cat.get_osm_filters())
    return filters


def match_tags_to_category(tags: dict, category_names: list[str] = None):
    """
    Match OSM tags to a category slug.

    Args:
        tags: Dictionary of OSM tags
        category_names: Optional list of category names to search (searches all enabled if None)

    Returns:
        Tuple of (category_slug, mapping, category_mappings) if match found, None otherwise
    """
    if category_names:
        categories = get_categories(category_names)
    else:
        categories = get_enabled_categories()

    # Search in priority order
    for cat in categories:
        result = cat.match_category(tags)
        if result:
            category_slug, mapping = result
            return (category_slug, mapping, cat)

    return None
