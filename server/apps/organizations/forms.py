from django.conf import settings
from django.utils.translation import gettext_lazy as _

OrganizationAdminFieldsets = [
    (
        _("Main Information"),
        {
            "fields": [
                "slug",
                ("name_i18n", "fullname_i18n"),
                "description_i18n",
                "url_i18n",
                "link_hut_pattern",
                "attribution_i18n",
                "logo",
                "order",
            ],
        },
    ),
    (
        f"{_('Name')} {_('Translations')} *",
        {
            "classes": ["collapse"],
            "fields": [
                tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
                tuple([f"fullname_{code}" for code in settings.LANGUAGE_CODES]),
            ],
        },
    ),
    (
        f"{_('Description')} {_('Translations')}",
        {
            "classes": ["collapse"],
            "fields": [f"description_{code}" for code in settings.LANGUAGE_CODES],
        },
    ),
    (
        f"{_('URL')} {_('Translations')}",
        {
            "classes": ["collapse"],
            "fields": [f"url_{code}" for code in settings.LANGUAGE_CODES],
        },
    ),
    (
        f"{_('Attribution')} {_('Translations')}",
        {
            "classes": ["collapse"],
            "fields": [f"attribution_{code}" for code in settings.LANGUAGE_CODES],
        },
    ),
    (
        _("Colors"),
        {
            # "classes": ["collapse"],
            "fields": [
                ("color_light", "color_dark"),
            ],
        },
    ),
    (
        _("Schemas"),
        {
            # "classes": ["collapse"],
            "fields": [
                "config",
                "props_schema",
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
# class OrganizationAdminForm(forms.ModelForm):
#    class Meta:
#        model = Organization
#        fieldsets = [
#            (
#                _("Main Information"),
#                {
#                    "fields": [
#                        ("slug", "name_i18n", "fullname_i18n"),
#                        "description_i18n",
#                        "url_i18n",
#                    ]
#                },
#            ),
#            (
#                _("Translations"),
#                {
#                    "classes": ["collapse"],
#                    "fields": [
#                        tuple([f"name_{code}" for code in settings.LANGUAGE_CODES]),
#                        tuple([f"fullname_{code}" for code in settings.LANGUAGE_CODES]),
#                    ]
#                    + [f"description_{code}" for code in settings.LANGUAGE_CODES]
#                    + [f"url_{code}" for code in settings.LANGUAGE_CODES],
#                },
#            ),
#            (
#                _("Symbols & Colors"),
#                {
#                    "fields": [
#                        "logo",
#                        ("color_light", "color_dark"),
#                    ]
#                },
#            ),
#        ]


# class TicketAdminForm(ModelForm):
#    first_name = forms.CharField(label="First name", max_length=32)
#    last_name = forms.CharField(label="Last name", max_length=32)
#
#    class Meta:
#        model = Ticket
#        fields = [
#            "concert",
#            "first_name",
#            "last_name",
#            "payment_method",
#            "is_active"
#        ]
#        widgets = {
#            "payment_method": RadioSelect(),
#        }
#
#    def __init__(self, *args, **kwargs):
#        instance = kwargs.get('instance')
#        initial = {}
#
#        if instance:
#            customer_full_name_split = instance.customer_full_name.split(" ", maxsplit=1)
#            initial = {
#                "first_name": customer_full_name_split[0],
#                "last_name": customer_full_name_split[1],
#            }
#
#        super().__init__(*args, **kwargs, initial=initial)
#
#    def save(self, commit=True):
#        self.instance.customer_full_name = self.cleaned_data["first_name"] + " " \
#                                            + self.cleaned_data["last_name"]
#        return super().save(commit)
