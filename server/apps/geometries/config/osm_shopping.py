"""OSM mappings for shopping category (Phase 3)."""

from .osm_base import CategoryMappings, OSMMapping


SHOPPING = CategoryMappings(
    category="shopping",
    detail_type="amenity",
    enabled=False,  # Phase 3 - not enabled by default
    mappings=[
        OSMMapping(
            osm_filters=["shop=clothes"],
            category_slug="shopping.clothes_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=shoes"],
            category_slug="shopping.shoe_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=hardware"],
            category_slug="shopping.hardware_store",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=books"],
            category_slug="shopping.bookshop",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=electronics"],
            category_slug="shopping.electronics_store",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=gift"],
            category_slug="shopping.gift_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
    ],
)
