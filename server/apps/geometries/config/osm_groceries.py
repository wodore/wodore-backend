"""OSM mappings for groceries category."""

from .osm_base import CategoryMappings, OSMMapping


def _vending_machine_condition(tags: dict) -> bool:
    """Only accept food/drink vending machines."""
    vending = tags.get("vending", "")
    return vending in ["food", "drinks", "sweets", "coffee", "cigarettes", "snacks"]


GROCERIES = CategoryMappings(
    category="groceries",
    detail_type="amenity",
    mappings=[
        OSMMapping(
            osm_filters=["shop=supermarket"],
            category_slug="groceries.supermarket",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[("shop=convenience", "shop=general")],  # OR
            category_slug="groceries.convenience",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=bakery"],
            category_slug="groceries.bakery",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=butcher"],
            category_slug="groceries.butcher",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=greengrocer"],
            category_slug="groceries.greengrocer",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=farm"],
            category_slug="groceries.farm_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=deli"],
            category_slug="groceries.deli",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=cheese"],
            category_slug="groceries.cheese_shop",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=dairy"],
            category_slug="groceries.dairy",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["shop=beverages"],
            category_slug="groceries.beverages",
            mapcomplete_theme="shops",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["amenity=vending_machine"],
            category_slug="groceries.vending_machine",
            condition=_vending_machine_condition,
            mapcomplete_theme="vending_machine",
            priority=0,
        ),
    ],
)
