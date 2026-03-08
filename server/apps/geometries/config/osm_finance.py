"""OSM mappings for finance category (Phase 2)."""

from .osm_base import CategoryMappings, OSMMapping


FINANCE = CategoryMappings(
    category="finance",
    detail_type="amenity",
    enabled=False,  # Phase 2 - not enabled by default
    mappings=[
        OSMMapping(
            osm_filters=["amenity=bank"],
            category_slug="finance.bank",
            mapcomplete_theme="banks",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=atm"],
            category_slug="finance.atm",
            mapcomplete_theme="banks",
            priority=0,
        ),
    ],
)
