from django.conf import settings
from django.utils.translation import gettext_lazy as _

ImageAdminFieldsets = [
    (
        _("Main Information"),
        {
            "classes": ["tab"],
            "fields": [
                "review_status",
                "image",
                ("caption_i18n", "license"),
                "tags",
            ],
        },
    ),
    (
        f"{_('Review')}",
        {
            "classes": ["tab"],
            "fields": [
                "review_comment",
            ],
        },
    ),
    (
        f"{_('Source')}",
        {
            "classes": ["tab"],
            "fields": [
                "author",
                "author_url",
                ("source_org", "source_ident"),
                "source_url",
                "source_url_raw",
            ],
        },
    ),
    (
        f"{_('Caption')} {_('Translations')}",
        {"classes": ["tab"], "fields": [f"caption_{code}" for code in settings.LANGUAGE_CODES]},
    ),
    (
        _("Meta"),
        {
            "classes": ["tab"],
            "fields": [
                ("image_meta"),
                ("granted_by_anonym", "granted_by_user", "granted_date"),
                ("uploaded_by_anonym", "uploaded_by_user", "uploaded_date"),
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
                "color",
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
