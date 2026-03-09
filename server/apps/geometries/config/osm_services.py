"""OSM mappings for services category (Phase 3)."""

from .osm_base import CategoryMappings, OSMMapping


SERVICES = CategoryMappings(
    category="services",
    detail_type="amenity",
    enabled=True,
    mappings=[
        OSMMapping(
            osm_filters=["shop=hairdresser"],
            category_slug="services.hairdresser",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=tailor"],
            category_slug="services.tailor",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=computer"],
            category_slug="services.computer_repair",
            mapcomplete_theme="shops",
            priority=1,  # Might be sales, lower priority
        ),
        OSMMapping(
            osm_filters=["amenity=veterinary"],
            category_slug="services.veterinary",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=laundry"],
            category_slug="services.laundry",
            mapcomplete_theme="shops",
            priority=0,
        ),
    ],
)
