"""OSM mappings for sport category (Phase 2).

See: https://wiki.openstreetmap.org/wiki/Key:sport
See: https://wiki.openstreetmap.org/wiki/Key:leisure
"""

from .osm_base import CategoryMappings, OSMMapping

SPORT = CategoryMappings(
    category="sport",
    detail_type="amenity",
    enabled=False,
    mappings=[
        OSMMapping(
            osm_filters=["leisure=sports_centre"],
            category_slug="sport.climbing_gym",
            mapcomplete_theme="sport",
            priority=1,  # Generic, lower priority
            importance_range=(25, 35, 50),
            default_name={
                "en": "Sports Centre",
                "de": "Sportzentrum",
                "fr": "Centre sportif",
                "it": "Centro sportivo",
            },
        ),
        OSMMapping(
            osm_filters=["sport=climbing"],
            category_slug="sport.climbing_gym",
            mapcomplete_theme="climbing",
            priority=0,
            importance_range=(30, 40, 55),
            default_name={
                "en": "Climbing Gym",
                "de": "Kletterhalle",
                "fr": "Salle d'escalade",
                "it": "Palestra arrampicata",
            },
        ),
        OSMMapping(
            osm_filters=["leisure=swimming_pool"],
            category_slug="sport.swimming_pool",
            mapcomplete_theme="sport",
            priority=0,
            importance_range=(30, 40, 55),
            default_name={
                "en": "Swimming Pool",
                "de": "Schwimmbad",
                "fr": "Piscine",
                "it": "Piscina",
            },
        ),
        OSMMapping(
            osm_filters=["leisure=fitness_centre"],
            category_slug="sport.fitness_center",
            mapcomplete_theme="sport",
            priority=0,
            importance_range=(25, 35, 50),
            default_name={
                "en": "Fitness Center",
                "de": "Fitnessstudio",
                "fr": "Centre de fitness",
                "it": "Palestra",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=ski_school"],
            category_slug="sport.ski_school",
            mapcomplete_theme="sport",
            priority=0,
            importance_range=(30, 40, 55),
            default_name={
                "en": "Ski School",
                "de": "Skischule",
                "fr": "École de ski",
                "it": "Scuola sci",
            },
        ),
        OSMMapping(
            osm_filters=["leisure=playground"],
            category_slug="sport.playground",
            mapcomplete_theme="playgrounds",
            priority=0,
            importance_range=(20, 30, 45),
            default_name={
                "en": "Playground",
                "de": "Spielplatz",
                "fr": "Aire de jeux",
                "it": "Parco giochi",
            },
        ),
        OSMMapping(
            osm_filters=["office=guide"],
            category_slug="sport.mountain_guide",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(35, 45, 60),
            default_name={
                "en": "Mountain Guide",
                "de": "Bergführer",
                "fr": "Guide de montagne",
                "it": "Guida alpina",
            },
        ),
        OSMMapping(
            osm_filters=[
                ("leisure=pitch", "sport=skateboard")
            ],  # AND logic - must have both tags
            category_slug="sport.skate_park",
            mapcomplete_theme="sport",
            priority=0,
            importance_range=(20, 30, 45),
            default_name={
                "en": "Skate Park",
                "de": "Skatepark",
                "fr": "Skatepark",
                "it": "Skatepark",
            },
        ),
    ],
)
