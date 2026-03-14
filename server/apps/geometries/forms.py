from django.conf import settings
from django.utils.translation import gettext_lazy as _

GeoPlaceAdminFieldsets = [
    (
        _("Main Information"),
        {
            "classes": ["tab"],
            "fields": [
                ("review_status", "is_public", "is_active"),
                ("slug", "name_i18n", "importance", "detail_type"),
                "review_comment",
                "description_i18n",
            ],
        },
    ),
    (
        f"{_('Name')} {_('Translations')} *",
        {
            "classes": ["tab"],
            "fields": [
                tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
            ],
        },
    ),
    (
        f"{_('Description')} {_('Translations')}",
        {
            "classes": ["tab"],
            "fields": [f"description_{code}" for code in settings.LANGUAGE_CODES],
        },
    ),
    (
        _("Geometry"),
        {
            "classes": ["tab"],
            "fields": [
                "location",
                "location_display",
                ("elevation", "country_code"),
                "shape",
            ],
        },
    ),
    (
        _("OSM Tags"),
        {
            "classes": ["tab"],
            "fields": [
                "osm_tags",
            ],
        },
    ),
    (
        _("Modifications"),
        {
            "classes": ["tab"],
            "fields": [
                "is_modified",
                "protected_fields",
            ],
        },
    ),
    (
        _("Timestamps"),
        {
            "classes": ["tab"],
            "fields": [
                ("created", "modified"),
            ],
        },
    ),
]
