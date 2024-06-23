from django.conf import settings
from django.utils.translation import gettext_lazy as _

ImageAdminFieldsets = [
    (
        _("Main Information"),
        {
            "fields": [
                "review_status",
                "image",
                "license",
                ("author", "source_org"),
                ("author_url", "source_url"),
                "caption_i18n",
                ("granted_by", "granted_date"),
                ("uploaded_by_anonym", "uploaded_by_user"),
                "tags",
            ],
        },
    ),
    (
        f"{_('Caption')} {_('Translations')}",
        {"classes": [""], "fields": [f"caption_{code}" for code in settings.LANGUAGE_CODES]},
    ),
    (
        _("Meta"),
        {
            "classes": [],
            "fields": [
                ("image_meta"),
            ],
        },
    ),
    (
        _("Timestamps"),
        {
            "classes": ["collapse"],
            "fields": [
                ("created", "modified"),
            ],
        },
    ),
]

ImageTagAdminFieldsets = [
    (
        _("Main Information"),
        {
            "fields": [
                "slug",
                "name_i18n",
            ],
        },
    ),
    (
        f"{_('Name')} {_('Translations')}",
        {"classes": [""], "fields": [f"name_{code}" for code in settings.LANGUAGE_CODES]},
    ),
    (
        _("Timestamps"),
        {
            "classes": ["collapse"],
            "fields": [
                ("created", "modified"),
            ],
        },
    ),
]
