"""OSM mappings for finance category (Phase 2).

See: https://wiki.openstreetmap.org/wiki/Key:amenity#Money
"""

from .osm_base import CategoryMappings, OSMMapping


FINANCE = CategoryMappings(
    category="finance",
    detail_type="amenity",
    enabled=True,
    mappings=[
        OSMMapping(
            osm_filters=["amenity=bank"],
            category_slug="finance.bank",
            mapcomplete_theme="banks",
            priority=0,
            importance_range=(30, 45, 60),
            default_name={"en": "Bank", "de": "Bank", "fr": "Banque", "it": "Banca"},
        ),
        OSMMapping(
            osm_filters=["amenity=atm"],
            category_slug="finance.atm",
            mapcomplete_theme="banks",
            priority=0,
            importance_range=(15, 25, 40),
            default_name={
                "en": "ATM",
                "de": "Geldautomat",
                "fr": "DAB",
                "it": "Bancomat",
            },
        ),
    ],
)
