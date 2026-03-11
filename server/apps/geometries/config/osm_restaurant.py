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
            default_name={
                "en": "Restaurant",
                "de": "Restaurant",
                "fr": "Restaurant",
                "it": "Ristorante",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=cafe"],
            category_slug="restaurant.cafe",
            mapcomplete_theme="food",
            priority=0,
            default_name={"en": "Cafe", "de": "Café", "fr": "Café", "it": "Caffè"},
        ),
        OSMMapping(
            osm_filters=[
                ("amenity=bar", "amenity=pub", "amenity=biergarten")
            ],  # OR - all drinking establishments
            category_slug="restaurant.pub",
            mapcomplete_theme="food",
            priority=0,
            default_name={"en": "Bar", "de": "Bar", "fr": "Bar", "it": "Bar"},
        ),
        OSMMapping(
            osm_filters=["amenity=fast_food"],
            category_slug="restaurant.fast_food",
            mapcomplete_theme="food",
            priority=0,
            default_name={
                "en": "Fast Food",
                "de": "Fast Food",
                "fr": "Fast Food",
                "it": "Fast Food",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=food_court"],
            category_slug="restaurant.food_court",
            mapcomplete_theme="food",
            priority=0,
            default_name={
                "en": "Food Court",
                "de": "Food Court",
                "fr": "Food Court",
                "it": "Food Court",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=ice_cream"],
            category_slug="restaurant.ice_cream",
            mapcomplete_theme="food",
            priority=0,
            default_name={
                "en": "Ice Cream",
                "de": "Eis",
                "fr": "Glacier",
                "it": "Gelateria",
            },
        ),
    ],
)
