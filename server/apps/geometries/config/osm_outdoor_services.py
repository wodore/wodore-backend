"""OSM mappings for outdoor_services category."""

from .osm_base import CategoryMappings, OSMMapping


OUTDOOR_SERVICES = CategoryMappings(
    category="outdoor_services",
    detail_type="amenity",
    mappings=[
        OSMMapping(
            osm_filters=[("shop=ski", "amenity=ski_rental")],  # OR
            category_slug="outdoor_services.ski_rental",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=bicycle"],
            category_slug="outdoor_services.bike_shop",
            mapcomplete_theme="cyclofix",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=bicycle_rental"],
            category_slug="outdoor_services.bike_rental",
            mapcomplete_theme="cyclofix",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=bicycle_repair_station"],
            category_slug="outdoor_services.bike_repair",
            mapcomplete_theme="cyclofix",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[
                ("shop=outdoor", "shop=sports")
            ],  # OR - outdoor and sports shops
            category_slug="outdoor_services.sports_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
    ],
)
