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
    "SITE_TITLE": "wodo.re",
    "SITE_HEADER": "Wodore Admin",
    "SITE_URL": "/",
    "SITE_ICON": lambda request: static(
        "main/images/favicon-32x32.png"
    ),  # both modes, optimise for 32px height
    # "SITE_LOGO": lambda request: static("main/images/favicon-32x32.png"),  # both modes, optimise for 32px height
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
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "sizes": "16x16",
            "type": "image/png",
            "href": lambda request: static("main/images/favicon-16x16.png"),
        },
        {
            "rel": "icon",
            "sizes": "32x32",
            "type": "image/png",
            "href": lambda request: static("main/images/favicon-32x32.png"),
        },
    ],
    "SHOW_HISTORY": True,  # show/hide "History" button, default: True
    "SHOW_VIEW_ON_SITE": True,  # show/hide "View on site" button, default: True
    "SHOW_LANGUAGES": True,
    "ENVIRONMENT": "server.core.utils.environment_callback",
    # "DASHBOARD_CALLBACK": "sample_app.dashboard_callback",
    # "LOGIN": {
    #    "image": lambda request: static("sample/login-bg.jpg"),
    #    "redirect_after": lambda request: reverse_lazy("admin:APP_MODEL_changelist"),
    # },
    "STYLES": [
        lambda request: static("/css/styles.css"),
        lambda request: static("/css/dj_map.css"),
    ],
    # "SCRIPTS": [
    #    lambda request: static("js/script.js"),
    # ],
    "COLORS": {
        "primary": {
            # accent
            # "100": "#e8c563",
            # "200": "#e3c04f",
            # "300": "#debd3a",
            # "400": "#d8bb27",
            # "500": "#bfab25",
            # "600": "#ad951f",
            # "700": "#998019",
            # "800": "#846a15",
            # "900": "#6f5610",
            "100": "#8fd6b7",
            "200": "#6dc59f",
            "300": "#4db286",
            "400": "#408c6b",
            "500": "#346751",
            "600": "#2a5b46",
            "700": "#224e3b",
            "800": "#1a4231",
            "900": "#133426",
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
                        "permission": lambda request: request.user.is_superuser,
                        # "permission": lambda request: request.user.has_perm("huts.view_hut"),
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
                        "permission": lambda request: request.user.has_perm(
                            "huts.view_hut"
                        ),
                    },
                    {
                        "title": _("Availability"),
                        "icon": "event_available",
                        "link": reverse_lazy(
                            "admin:availability_hutavailability_changelist"
                        ),
                        "permission": lambda request: request.user.has_perm(
                            "availability.view_hutavailability"
                        ),
                    },
                    {
                        "title": _("Owners"),
                        "icon": "location_away",
                        "link": reverse_lazy("admin:owners_owner_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "owners.view_owner"
                        ),
                    },
                    {
                        "title": _("Organizations"),
                        "icon": "corporate_fare",
                        "link": reverse_lazy(
                            "admin:organizations_organization_changelist"
                        ),
                        "permission": lambda request: request.user.has_perm(
                            "organizations.view_organization"
                        ),
                    },
                    {
                        "title": _("Contacts"),
                        "icon": "contacts",
                        "link": reverse_lazy("admin:contacts_contact_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "contacts.change_contact"
                        ),
                    },
                ],
            },
            {
                "title": None,  # lambda request: _("Users") if request.user.is_superuser else None,  # TODO: does not work
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("Feedbacks"),
                        "icon": "feedback",
                        "link": reverse_lazy("admin:feedbacks_feedback_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "feedbacks.change_feedback"
                        ),
                    },
                    {
                        "title": _("Images"),
                        "icon": "photo_library",
                        "link": reverse_lazy("admin:images_image_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "images.change_image"
                        ),
                    },
                    {
                        "title": _("Licenses"),
                        "icon": "copyright",
                        "link": reverse_lazy("admin:licenses_license_changelist"),
                        "permission": lambda request: request.user.has_perm(
                            "licenses.change_feedback"
                        ),
                    },
                ],
            },
            {
                "title": None,  # lambda request: _("Users") if request.user.is_superuser else None,  # TODO: does not work
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("Zitadel Users"),
                        "icon": "manage_accounts",
                        "link": "https://iam.wodore.com/ui/console/users",
                        "permission": lambda request: request.user.is_superuser,
                        "target": "_blank",
                    },
                    {
                        "title": _("Groups"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": _("External Links"),
                "separator": True,  # Top border
                "items": [
                    {
                        "title": _("API"),
                        "badge": "v1",
                        "icon": "api",
                        "link": "/v1/docs",
                        "permission": lambda request: request.user.is_superuser,
                        "target": "_blank",
                    },
                    {
                        "title": _("Frontend (wodo.re)"),
                        "icon": "captive_portal",
                        "link": "https://wodo.re",
                        "target": "_blank",
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
                    "permission": lambda request: request.user.has_perm(
                        "huts.view_hut"
                    ),
                },
                {
                    "title": _("Types"),
                    "link": reverse_lazy("admin:huts_huttype_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "huts.view_huttype"
                    ),
                },
                {
                    "title": _("Sources"),
                    "link": reverse_lazy("admin:huts_hutsource_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "huts.view_hutsource"
                    ),
                },
            ],
        },
        {
            "models": [
                "availability.hutavailability",
                "availability.hutavailabilityhistory",
            ],
            "items": [
                {
                    "title": _("Availability"),
                    "link": reverse_lazy(
                        "admin:availability_hutavailability_changelist"
                    ),
                    "permission": lambda request: request.user.has_perm(
                        "availability.view_hutavailability"
                    ),
                },
                {
                    "title": _("History"),
                    "link": reverse_lazy(
                        "admin:availability_hutavailabilityhistory_changelist"
                    ),
                    "permission": lambda request: request.user.has_perm(
                        "availability.view_hutavailabilityhistory"
                    ),
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
                    "permission": lambda request: request.user.has_perm(
                        "contacts.view_contacts"
                    ),
                },
                {
                    "title": _("Contact Functions"),
                    "link": reverse_lazy("admin:contacts_contactfunction_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "contacts.view_contactfunctions"
                    ),
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
                    "permission": lambda request: request.user.has_perm(
                        "owners.view_owner"
                    ),
                },
                {
                    "title": _("with Contacts"),
                    "link": reverse_lazy(
                        "admin:owners_ownercontactassociation_changelist"
                    ),
                    "permission": lambda request: request.user.has_perm(
                        "owners.view_ownercontactassociation"
                    ),
                },
                {
                    "title": _("with Huts"),
                    "link": reverse_lazy("admin:owners_ownerhutproxy_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "owners.view_ownerhutproxy"
                    ),
                },
            ],
        },
        {
            "models": [
                "images.image",
                "images.imagetag",
            ],
            "items": [
                {
                    "title": _("Images"),
                    "link": reverse_lazy("admin:images_image_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "images.view_images"
                    ),
                },
                {
                    "title": _("Image Tags"),
                    "link": reverse_lazy("admin:images_imagetag_changelist"),
                    "permission": lambda request: request.user.has_perm(
                        "images.view_imagetags"
                    ),
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
