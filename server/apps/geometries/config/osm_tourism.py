"""OSM mappings for tourism category.

See: https://wiki.openstreetmap.org/wiki/Key:tourism
See: https://wiki.openstreetmap.org/wiki/Key:attraction
"""

from .osm_base import CategoryMappings, OSMMapping

TOURISM = CategoryMappings(
    category="tourism",
    detail_type="amenity",
    mappings=[
        # Information - all types combined
        OSMMapping(
            osm_filters=[
                ("tourism=information", "information=office"),
                ("tourism=information", "information=visitor_centre"),
                ("tourism=information", "information=board", "board_type=notice"),
                ("tourism=information", "information=map"),
            ],
            category_slug="tourism.information",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(15, 35, 55),
            default_name={
                "en": "Information",
                "de": "Information",
                "fr": "Information",
                "it": "Informazioni",
            },
        ),
        OSMMapping(
            osm_filters=["tourism=viewpoint"],
            category_slug="tourism.viewpoint",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(35, 50, 65),
            default_name={
                "en": "Viewpoint",
                "de": "Aussichtspunkt",
                "fr": "Point de vue",
                "it": "Punto panoramico",
            },
        ),
        OSMMapping(
            osm_filters=["tourism=museum"],
            category_slug="tourism.museum",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(40, 55, 70),
            default_name={"en": "Museum", "de": "Museum", "fr": "Musée", "it": "Museo"},
        ),
        OSMMapping(
            osm_filters=["tourism=attraction"],
            category_slug="tourism.attraction",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(35, 50, 65),
            default_name={
                "en": "Attraction",
                "de": "Sehenswürdigkeit",
                "fr": "Attraction",
                "it": "Attrazione",
            },
        ),
        OSMMapping(
            osm_filters=["tourism=artwork"],
            category_slug="tourism.artwork",
            mapcomplete_theme="artwork",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Artwork",
                "de": "Kunstwerk",
                "fr": "Œuvre d'art",
                "it": "Opera d'arte",
            },
        ),
        OSMMapping(
            osm_filters=["historic=memorial"],
            category_slug="tourism.memorial",
            mapcomplete_theme="tourism",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={
                "en": "Memorial",
                "de": "Gedenkstätte",
                "fr": "Mémorial",
                "it": "Memoriale",
            },
        ),
    ],
)
