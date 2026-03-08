"""OSM mappings for health_and_emergency category."""

from .osm_base import CategoryMappings, OSMMapping


HEALTH_AND_EMERGENCY = CategoryMappings(
    category="health_and_emergency",
    detail_type="amenity",
    mappings=[
        # Emergency services (highest priority)
        OSMMapping(
            osm_filters=["amenity=fire_station"],
            category_slug="health_and_emergency.fire_station",
            mapcomplete_theme="emergency",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=police"],
            category_slug="health_and_emergency.police",
            mapcomplete_theme="emergency",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["emergency=mountain_rescue"],
            category_slug="health_and_emergency.mountain_rescue",
            mapcomplete_theme="emergency",
            priority=0,
        ),
        # Healthcare
        OSMMapping(
            osm_filters=["amenity=hospital"],
            category_slug="health_and_emergency.hospital",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=clinic"],
            category_slug="health_and_emergency.clinic",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=doctors"],
            category_slug="health_and_emergency.doctor",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=dentist"],
            category_slug="health_and_emergency.dentist",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=pharmacy"],
            category_slug="health_and_emergency.pharmacy",
            mapcomplete_theme="healthcare",
            priority=0,
        ),
    ],
)
