"""OSM mappings for transport category."""

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
        ),
        OSMMapping(
            osm_filters=["amenity=bus_station"],
            category_slug="transport.bus_station",
            mapcomplete_theme="transit",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["railway=station"],
            category_slug="transport.train_station",
            mapcomplete_theme="transit",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["railway=halt"],
            category_slug="transport.train_station",
            mapcomplete_theme="transit",
            priority=1,  # Lower priority, same category as station
        ),
        OSMMapping(
            osm_filters=["aerialway=station"],
            category_slug="transport.cable_car",
            mapcomplete_theme="transit",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["aerialway=gondola"],
            category_slug="transport.gondola",
            mapcomplete_theme="transit",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["aerialway=chair_lift"],
            category_slug="transport.chairlift",
            mapcomplete_theme="transit",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["railway=funicular"],
            category_slug="transport.funicular",
            mapcomplete_theme="transit",
            priority=0,
        ),
    ],
)
