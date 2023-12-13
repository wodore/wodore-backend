"""
This file contains a definition for unfold admin

Read more about it:
https://github.com/unfoldadmin/django-unfold
https://github.com/unfoldadmin/django-unfold#configuration

"""

from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


UNFOLD = {
    "SITE_TITLE": None,
    "SITE_HEADER": None,
    "SITE_URL": "/",
    # "SITE_ICON": lambda request: static("icon.svg"),  # both modes, optimise for 32px height
    # "SITE_ICON": {
    #    "light": lambda request: static("icon-light.svg"),  # light mode
    #    "dark": lambda request: static("icon-dark.svg"),  # dark mode
    # },
    ## "SITE_LOGO": lambda request: static("logo.svg"),  # both modes, optimise for 32px height
    # "SITE_LOGO": {
    #    "light": lambda request: static("logo-light.svg"),  # light mode
    #    "dark": lambda request: static("logo-dark.svg"),  # dark mode
    # },
    "SITE_SYMBOL": "cottage",  # symbol from icon set
    "SHOW_HISTORY": True,  # show/hide "History" button, default: True
    "SHOW_VIEW_ON_SITE": True,  # show/hide "View on site" button, default: True
    "ENVIRONMENT": "server.core.utils.environment_callback",
    # "DASHBOARD_CALLBACK": "sample_app.dashboard_callback",
    # "LOGIN": {
    #    "image": lambda request: static("sample/login-bg.jpg"),
    #    "redirect_after": lambda request: reverse_lazy("admin:APP_MODEL_changelist"),
    # },
    "STYLES": [
        lambda request: static("/css/styles.css"),
    ],
    # "SCRIPTS": [
    #    lambda request: static("js/script.js"),
    # ],
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
    "EXTENSIONS": {
        "modeltranslation": {
            "flags": {
                "en": "🇬🇧",
                "fr": "🇫🇷",
                "nl": "🇧🇪",
            },
        },
    },
    "SIDEBAR": {
        "show_search": False,  # Search in applications and models names
        "show_all_applications": True,  # Dropdown with all applications and models
        "navigation": [
            {
                # "title": _("Navigation"),
                "separator": False,  # Top border
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",  # Supported icon set: https://fonts.google.com/icons
                        "link": reverse_lazy("admin:index"),
                        # "badge": "sample_app.badge_callback",
                        # "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": None,  # _("App"),
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("Huts"),
                        "icon": "house",
                        "link": reverse_lazy("admin:huts_hut_changelist"),
                    },
                    {
                        "title": _("Owners"),
                        "icon": "location_away",
                        "link": reverse_lazy("admin:owners_owner_changelist"),
                    },
                    {
                        "title": _("Organizations"),
                        "icon": "corporate_fare",
                        "link": reverse_lazy("admin:organizations_organization_changelist"),
                    },
                    {
                        "title": _("Contacts"),
                        "icon": "contacts",
                        "link": reverse_lazy("admin:contacts_contact_changelist"),
                    },
                ],
            },
            {
                "title": None,  # lambda request: _("Users") if request.user.is_superuser else None,  # TODO: does not work
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": _("Groups"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": _("Help"),
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("API"),
                        "badge": "v1",
                        "icon": "api",
                        "link": "/api/v1/docs",  # todo use name # todo change unfold/helpers/app_list.html tempalte to use target=
                    },
                ],
            },
        ],
    },
    "TABS": [
        {
            "models": [
                "huts.hut",
                "huts.huttype",
                "huts.hutsource",
            ],
            "items": [
                {
                    "title": _("Huts"),
                    "link": reverse_lazy("admin:huts_hut_changelist"),
                },
                {
                    "title": _("Types"),
                    "link": reverse_lazy("admin:huts_huttype_changelist"),
                },
                {
                    "title": _("Sources"),
                    "link": reverse_lazy("admin:huts_hutsource_changelist"),
                },
            ],
        },
        {
            "models": [
                "contacts.contact",
                "contacts.contactfunction",
            ],
            "items": [
                {
                    "title": _("Contacts"),
                    "link": reverse_lazy("admin:contacts_contact_changelist"),
                },
                {
                    "title": _("Contact Functions"),
                    "link": reverse_lazy("admin:contacts_contactfunction_changelist"),
                },
            ],
        },
        {
            "models": [
                "owners.owner",
                "owners.ownercontactassociation",
                "owners.ownerhutproxy",
            ],
            "items": [
                {
                    "title": _("Owners"),
                    "link": reverse_lazy("admin:owners_owner_changelist"),
                },
                {
                    "title": _("with Contacts"),
                    "link": reverse_lazy("admin:owners_ownercontactassociation_changelist"),
                },
                {
                    "title": _("with Huts"),
                    "link": reverse_lazy("admin:owners_ownerhutproxy_changelist"),
                },
            ],
        },
    ],
}


def dashboard_callback(request, context):
    """
    Callback to prepare custom variables for index template which is used as dashboard
    template. It can be overridden in application by creating custom admin/index.html.
    """
    context.update(
        {
            "sample": "example",  # this will be injected into templates/admin/index.html
        }
    )
    return context


def badge_callback(request):
    return 3


def permission_callback(request):
    return request.user.has_perm("sample_app.change_model")
