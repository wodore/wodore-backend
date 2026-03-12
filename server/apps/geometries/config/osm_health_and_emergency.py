"""OSM mappings for health_and_emergency category.

See: https://wiki.openstreetmap.org/wiki/Key:amenity#Health_and_emergency
"""

from .osm_base import CategoryMappings, OSMMapping

HEALTH_AND_EMERGENCY = CategoryMappings(
    category="health_and_emergency",
    detail_type="amenity",
    mappings=[
        # Emergency services (highest priority)
        OSMMapping(
            osm_filters=["amenity=fire_station"],
            category_slug="health_and_emergency.fire_station",
            mapcomplete_theme="emergency",
            priority=0,
            importance_range=(40, 55, 70),
            default_name={
                "en": "Fire Station",
                "de": "Feuerwehr",
                "fr": "Caserne de pompiers",
                "it": "Stazione dei pompieri",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=police"],
            category_slug="health_and_emergency.police",
            mapcomplete_theme="emergency",
            priority=0,
            importance_range=(40, 55, 70),
            default_name={
                "en": "Police",
                "de": "Polizei",
                "fr": "Police",
                "it": "Polizia",
            },
        ),
        OSMMapping(
            osm_filters=["emergency=mountain_rescue"],
            category_slug="health_and_emergency.mountain_rescue",
            mapcomplete_theme="emergency",
            priority=0,
            importance_range=(45, 60, 75),
            default_name={
                "en": "Mountain Rescue",
                "de": "Bergwacht",
                "fr": "Secours en montagne",
                "it": "Soccorso alpino",
            },
        ),
        # Healthcare
        OSMMapping(
            osm_filters=["amenity=hospital"],
            category_slug="health_and_emergency.hospital",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(45, 60, 75),
            default_name={
                "en": "Hospital",
                "de": "Krankenhaus",
                "fr": "Hôpital",
                "it": "Ospedale",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=clinic"],
            category_slug="health_and_emergency.clinic",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(35, 50, 65),
            default_name={
                "en": "Clinic",
                "de": "Klinik",
                "fr": "Clinique",
                "it": "Clinica",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=doctors"],
            category_slug="health_and_emergency.doctor",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Doctor",
                "de": "Arzt",
                "fr": "Médecin",
                "it": "Medico",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=dentist"],
            category_slug="health_and_emergency.dentist",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Dentist",
                "de": "Zahnarzt",
                "fr": "Dentiste",
                "it": "Dentista",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=pharmacy"],
            category_slug="health_and_emergency.pharmacy",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(35, 50, 65),
            default_name={
                "en": "Pharmacy",
                "de": "Apotheke",
                "fr": "Pharmacie",
                "it": "Farmacia",
            },
        ),
        OSMMapping(
            osm_filters=["shop=optician"],
            category_slug="health_and_emergency.optician",
            mapcomplete_theme="healthcare",
            priority=0,
            importance_range=(25, 35, 50),
            default_name={
                "en": "Optician",
                "de": "Optiker",
                "fr": "Opticien",
                "it": "Ottico",
            },
        ),
    ],
)
