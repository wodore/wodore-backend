"""OSM mappings for shopping category (Phase 3)."""

from .osm_base import CategoryMappings, OSMMapping


SHOPPING = CategoryMappings(
    category="shopping",
    detail_type="amenity",
    enabled=True,
    mappings=[
        OSMMapping(
            osm_filters=["shop=clothes"],
            category_slug="shopping.clothes",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=shoes"],
            category_slug="shopping.shoe",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=hardware"],
            category_slug="shopping.hardware",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=books"],
            category_slug="shopping.books",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=electronics"],
            category_slug="shopping.electronics",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=jewelry"],
            category_slug="shopping.jewelry",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=toys"],
            category_slug="shopping.toys",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[("shop=gift", "shop=souvenir")],  # OR
            category_slug="shopping.gift",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[
                ("shop=general", "shop=variety_store", "shop=department_store")
            ],  # OR
            category_slug="shopping.store",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=mall"],
            category_slug="shopping.mall",
            mapcomplete_theme="shops",
            priority=0,
        ),
    ],
)
