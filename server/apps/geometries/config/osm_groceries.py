"""OSM mappings for groceries category.

See: https://wiki.openstreetmap.org/wiki/Key:shop
"""

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
            importance_range=(30, 45, 60),
            default_name={
                "en": "Supermarket",
                "de": "Supermarkt",
                "fr": "Supermarché",
                "it": "Supermercato",
            },
        ),
        OSMMapping(
            osm_filters=[("shop=convenience", "shop=general")],  # OR
            category_slug="groceries.convenience",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(20, 35, 50),
            default_name={
                "en": "Grocery",
                "de": "Nahrungsmittel",
                "fr": "Épicerie",
                "it": "Alimentari",
            },
        ),
        OSMMapping(
            osm_filters=["shop=bakery"],
            category_slug="groceries.bakery",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(20, 35, 50),
            default_name={
                "en": "Bakery",
                "de": "Bäckerei",
                "fr": "Boulangerie",
                "it": "Panetteria",
            },
        ),
        OSMMapping(
            osm_filters=["shop=butcher"],
            category_slug="groceries.butcher",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(20, 30, 45),
            default_name={
                "en": "Butcher",
                "de": "Metzgerei",
                "fr": "Boucherie",
                "it": "Macelleria",
            },
        ),
        OSMMapping(
            osm_filters=["shop=farm"],
            category_slug="groceries.farm",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(25, 35, 50),
            default_name={
                "en": "Farm",
                "de": "Hofladen",
                "fr": "Ferme",
                "it": "Fattoria",
            },
        ),
        OSMMapping(
            osm_filters=[
                ("shop=greengrocer", "shop=deli", "shop=cheese", "shop=dairy")
            ],  # OR - specialty dairy/produce
            category_slug="groceries.dairy",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(20, 30, 45),
            default_name={
                "en": "Deli",
                "de": "Feinkost",
                "fr": "Épicerie",
                "it": "Gastronomia",
            },
        ),
        OSMMapping(
            osm_filters=["shop=beverages"],
            category_slug="groceries.beverages",
            mapcomplete_theme="shops",
            priority=0,
            importance_range=(20, 30, 45),
            default_name={
                "en": "Beverages",
                "de": "Getränke",
                "fr": "Boissons",
                "it": "Bevande",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=vending_machine"],
            category_slug="groceries.vending_machine",
            condition=_vending_machine_condition,
            mapcomplete_theme="vending_machine",
            priority=0,
            importance_range=(5, 10, 20),
            default_name={
                "en": "Vending Machine",
                "de": "Automat",
                "fr": "Distributeur",
                "it": "Distributore",
            },
        ),
    ],
)
