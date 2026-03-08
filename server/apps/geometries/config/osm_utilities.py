"""OSM mappings for utilities category (Phase 2)."""

from .osm_base import CategoryMappings, OSMMapping


UTILITIES = CategoryMappings(
    category="utilities",
    detail_type="amenity",
    enabled=False,  # Phase 2 - not enabled by default
    mappings=[
        OSMMapping(
            osm_filters=["amenity=toilets"],
            category_slug="utilities.toilets",
            mapcomplete_theme="toilets",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=drinking_water"],
            category_slug="utilities.drinking_water",
            mapcomplete_theme="drinking_water",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=shower"],
            category_slug="utilities.shower",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=waste_disposal"],
            category_slug="utilities.waste_disposal",
            mapcomplete_theme="waste",
            priority=0,
        ),
    ],
)
