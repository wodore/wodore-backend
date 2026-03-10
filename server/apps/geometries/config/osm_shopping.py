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
            default_name={
                "en": "Clothing Store",
                "de": "Kleidung",
                "fr": "Magasin de vêtements",
                "it": "Abbigliamento",
            },
        ),
        OSMMapping(
            osm_filters=["shop=shoes"],
            category_slug="shopping.shoe",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Shoe Store",
                "de": "Schuhe",
                "fr": "Chaussures",
                "it": "Scarpe",
            },
        ),
        OSMMapping(
            osm_filters=["shop=hardware"],
            category_slug="shopping.hardware",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Hardware Store",
                "de": "Baumarkt",
                "fr": "Quincaillerie",
                "it": "Ferramenta",
            },
        ),
        OSMMapping(
            osm_filters=["shop=books"],
            category_slug="shopping.books",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Bookstore",
                "de": "Bücherhandlung",
                "fr": "Librairie",
                "it": "Libreria",
            },
        ),
        OSMMapping(
            osm_filters=["shop=electronics"],
            category_slug="shopping.electronics",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Electronics",
                "de": "Elektronik",
                "fr": "Électronique",
                "it": "Elettronica",
            },
        ),
        OSMMapping(
            osm_filters=["shop=jewelry"],
            category_slug="shopping.jewelry",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Jewelry",
                "de": "Juwelier",
                "fr": "Bijouterie",
                "it": "Gioielleria",
            },
        ),
        OSMMapping(
            osm_filters=["shop=toys"],
            category_slug="shopping.toys",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Toy Store",
                "de": "Spielwaren",
                "fr": "Jouets",
                "it": "Giochi",
            },
        ),
        OSMMapping(
            osm_filters=[("shop=gift", "shop=souvenir")],  # OR
            category_slug="shopping.gift",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Gift Shop",
                "de": "Geschenkeladen",
                "fr": "Boutique cadeaux",
                "it": "Negozio souvenir",
            },
        ),
        OSMMapping(
            osm_filters=[
                ("shop=general", "shop=variety_store", "shop=department_store")
            ],  # OR
            category_slug="shopping.store",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Store",
                "de": "Geschäft",
                "fr": "Magasin",
                "it": "Negozio",
            },
        ),
        OSMMapping(
            osm_filters=["shop=mall"],
            category_slug="shopping.mall",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Mall",
                "de": "Einkaufszentrum",
                "fr": "Centre commercial",
                "it": "Centro commerciale",
            },
        ),
    ],
)
