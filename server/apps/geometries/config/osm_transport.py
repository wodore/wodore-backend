"""OSM mappings for transport category.

See: https://wiki.openstreetmap.org/wiki/Key:public_transport
See: https://wiki.openstreetmap.org/wiki/Key:amenity#Transportation
"""

from .osm_base import CategoryMappings, OSMMapping

TRANSPORT = CategoryMappings(
    category="transport",
    detail_type="transport",  # Uses TransportDetail
    enabled=False,
    mappings=[
        OSMMapping(
            osm_filters=["highway=bus_stop"],
            category_slug="transport.bus_stop",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(15, 25, 40),
            default_name={
                "en": "Bus Stop",
                "de": "Bushaltestelle",
                "fr": "Arrêt de bus",
                "it": "Fermata autobus",
            },
        ),
        OSMMapping(
            osm_filters=["amenity=bus_station"],
            category_slug="transport.bus_station",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Bus Station",
                "de": "Busbahnhof",
                "fr": "Gare routière",
                "it": "Stazione autobus",
            },
        ),
        OSMMapping(
            osm_filters=["railway=station"],
            category_slug="transport.train_station",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(40, 55, 70),
            default_name={
                "en": "Train Station",
                "de": "Bahnhof",
                "fr": "Gare",
                "it": "Stazione ferroviaria",
            },
        ),
        OSMMapping(
            osm_filters=["railway=halt"],
            category_slug="transport.train_station",
            mapcomplete_theme="transit",
            priority=1,  # Lower priority, same category as station
            importance_range=(25, 35, 50),
        ),
        OSMMapping(
            osm_filters=["aerialway=station"],
            category_slug="transport.cable_car",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(35, 50, 65),
            default_name={
                "en": "Cable Car Station",
                "de": "Seilbahnstation",
                "fr": "Station de téléphérique",
                "it": "Stazione funivia",
            },
        ),
        OSMMapping(
            osm_filters=["aerialway=gondola"],
            category_slug="transport.gondola",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Gondola",
                "de": "Gondelbahn",
                "fr": "Télécabine",
                "it": "Funivia",
            },
        ),
        OSMMapping(
            osm_filters=["aerialway=chair_lift"],
            category_slug="transport.chairlift",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Chairlift",
                "de": "Sessellift",
                "fr": "Télésiège",
                "it": "Seggiovia",
            },
        ),
        OSMMapping(
            osm_filters=["railway=funicular"],
            category_slug="transport.funicular",
            mapcomplete_theme="transit",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Funicular",
                "de": "Standseilbahn",
                "fr": "Funiculaire",
                "it": "Funicolare",
            },
        ),
    ],
)
