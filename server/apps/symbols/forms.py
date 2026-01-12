from django.utils.translation import gettext_lazy as _

SymbolAdminFieldsets = [
    (
        _("Main Information"),
        {
            "classes": ["tab"],
            "fields": [
                ("review_status", "is_active"),
                ("slug", "style"),
                ("svg_file", "license"),
                "svg_preview_inline",
                "search_text",
            ],
        },
    ),
    (
        _("Review"),
        {
            "classes": ["tab"],
            "fields": [
                "review_comment",
            ],
        },
    ),
    (
        _("Source"),
        {
            "classes": ["tab"],
            "fields": [
                "author",
                "author_url",
                ("source_org", "source_ident"),
                "source_url",
            ],
        },
    ),
    (
        _("Meta"),
        {
            "classes": ["tab"],
            "fields": [
                ("uploaded_by_user", "uploaded_by_anonym", "uploaded_date"),
                ("created", "modified"),
            ],
        },
    ),
]

# TODO: Add SymbolTagAdminFieldsets if tags are implemented in the future
# SymbolTagAdminFieldsets = [
#     (
#         _("Main Information"),
#         {
#             "fields": [
#                 "slug",
#                 "name_i18n",
#                 "color",
#             ],
#         },
#     ),
#     (
#         f"{_('Name')} {_('Translations')}",
#         {
#             "classes": [""],
#             "fields": [f"name_{code}" for code in settings.LANGUAGE_CODES],
#         },
#     ),
#     (
#         _("Timestamps"),
#         {
#             "classes": ["collapse"],
#             "fields": [
#                 ("created", "modified"),
#             ],
#         },
#     ),
# ]
