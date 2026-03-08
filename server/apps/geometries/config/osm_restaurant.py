"""OSM mappings for restaurant category."""

from .osm_base import CategoryMappings, OSMMapping


RESTAURANT = CategoryMappings(
    category="restaurant",
    detail_type="amenity",
    mappings=[
        OSMMapping(
            osm_filters=["amenity=restaurant"],
            category_slug="restaurant.restaurant",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=cafe"],
            category_slug="restaurant.cafe",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=bar"],
            category_slug="restaurant.bar",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=pub"],
            category_slug="restaurant.pub",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=fast_food"],
            category_slug="restaurant.fast_food",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=food_court"],
            category_slug="restaurant.food_court",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=ice_cream"],
            category_slug="restaurant.ice_cream",
            mapcomplete_theme="food",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=biergarten"],
            category_slug="restaurant.pub",  # Map biergarten to pub
            mapcomplete_theme="food",
            priority=1,  # Lower priority than direct pub mapping
        ),
    ],
)
