"""OSM mappings for tourism category."""

from .osm_base import CategoryMappings, OSMMapping


TOURISM = CategoryMappings(
    category="tourism",
    detail_type="amenity",
    mappings=[
        OSMMapping(
            osm_filters=["tourism=information"],
            category_slug="tourism.information",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["tourism=viewpoint"],
            category_slug="tourism.viewpoint",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["tourism=museum"],
            category_slug="tourism.museum",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["tourism=attraction"],
            category_slug="tourism.attraction",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["tourism=artwork"],
            category_slug="tourism.artwork",
            mapcomplete_theme="artwork",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["historic=memorial"],
            category_slug="tourism.memorial",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=["information=guidepost"],
            category_slug="tourism.hiking_post",
            mapcomplete_theme="tourism",
            priority=0,
        ),
        OSMMapping(
            osm_filters=[
                ("information=board", "information=office", "information=map")
            ],  # OR - hiking information infrastructure
            category_slug="tourism.information",
            mapcomplete_theme="tourism",
            priority=1,  # Lower priority than generic tourism=information
        ),
    ],
)
