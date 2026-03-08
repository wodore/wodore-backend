"""OSM mappings for sport category (Phase 2)."""

from .osm_base import CategoryMappings, OSMMapping


SPORT = CategoryMappings(
    category="sport",
    detail_type="amenity",
    enabled=True,
    mappings=[
        OSMMapping(
            osm_filters=["leisure=sports_centre"],
            category_slug="sport.climbing_gym",
            mapcomplete_theme="sport",
            priority=1,  # Generic, lower priority
        ),
        OSMMapping(
            osm_filters=["sport=climbing"],
            category_slug="sport.climbing_gym",
            mapcomplete_theme="climbing",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["leisure=swimming_pool"],
            category_slug="sport.swimming_pool",
            mapcomplete_theme="sport",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["leisure=fitness_centre"],
            category_slug="sport.fitness_center",
            mapcomplete_theme="sport",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=ski_school"],
            category_slug="sport.ski_school",
            mapcomplete_theme="sport",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["leisure=playground"],
            category_slug="sport.playground",
            mapcomplete_theme="playgrounds",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["office=guide"],
            category_slug="sport.mountain_guide",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[
                ("leisure=pitch", "sport=skateboard")
            ],  # AND logic - must have both tags
            category_slug="sport.skate_park",
            mapcomplete_theme="sport",
            priority=0,
        ),
    ],
)
