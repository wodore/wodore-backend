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
            default_name={
                "en": "Ski Rental",
                "de": "Skiverleih",
                "fr": "Location de ski",
                "it": "Noleggio sci",
            },
            importance_range=(30, 50, 75),  # Min, base, max
        ),
        OSMMapping(
            osm_filters=["shop=bicycle"],
            category_slug="outdoor_services.bike_shop",
            mapcomplete_theme="cyclofix",
            priority=0,
            default_name={
                "en": "Bike Shop",
                "de": "Fahrradladen",
                "fr": "Magasin de vélos",
                "it": "Negozio di biciclette",
            },
            importance_range=(35, 55, 80),
        ),
        OSMMapping(
            osm_filters=["amenity=bicycle_rental"],
            category_slug="outdoor_services.bike_rental",
            mapcomplete_theme="cyclofix",
            priority=0,
            default_name={
                "en": "Bike Rental",
                "de": "Fahrradverleih",
                "fr": "Location de vélos",
                "it": "Noleggio biciclette",
            },
            importance_range=(35, 60, 85),
        ),
        OSMMapping(
            osm_filters=["amenity=bicycle_repair_station"],
            category_slug="outdoor_services.bike_repair",
            mapcomplete_theme="cyclofix",
            priority=0,
            default_name={
                "en": "Bike Repair",
                "de": "Fahrradwerkstatt",
                "fr": "Réparation vélos",
                "it": "Riparazione biciclette",
            },
            importance_range=(20, 40, 60),
        ),
        OSMMapping(
            osm_filters=[
                ("shop=outdoor", "shop=sports")
            ],  # OR - outdoor and sports shops
            category_slug="outdoor_services.sports_shop",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Sports Shop",
                "de": "Sportgeschäft",
                "fr": "Magasin de sports",
                "it": "Negozio sportivo",
            },
            importance_range=(40, 60, 85),
        ),
    ],
)
