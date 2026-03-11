"""OSM mappings for automotive category (Phase 2)."""

from .osm_base import CategoryMappings, OSMMapping

AUTOMOTIVE = CategoryMappings(
    category="automotive",
    detail_type="amenity",
    enabled=True,
    mappings=[
        OSMMapping(
            osm_filters=["amenity=parking"],
            category_slug="automotive.parking",
            mapcomplete_theme="parking",
            priority=0,
            default_name={
                "en": "Parking",
                "de": "Parkplatz",
                "fr": "Parking",
                "it": "Parcheggio",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=fuel"],
            category_slug="automotive.fuel",
            mapcomplete_theme="charging_station",
            priority=0,
            default_name={
                "en": "Fuel Station",
                "de": "Tankstelle",
                "fr": "Station-service",
                "it": "Stazione di servizio",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=charging_station"],
            category_slug="automotive.charging_station",
            mapcomplete_theme="charging_station",
            priority=0,
            default_name={
                "en": "Charging Station",
                "de": "Ladestation",
                "fr": "Station de recharge",
                "it": "Stazione di ricarica",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=car_wash"],
            category_slug="automotive.car_wash",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Car Wash",
                "de": "Autowaschanlage",
                "fr": "Station de lavage",
                "it": "Autolavaggio",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=car_rental"],
            category_slug="automotive.car_rental",
            mapcomplete_theme="shops",
            priority=0,
            default_name={
                "en": "Car Rental",
                "de": "Autovermietung",
                "fr": "Location de voiture",
                "it": "Autonoleggio",
            },
        ),
    ],
)
