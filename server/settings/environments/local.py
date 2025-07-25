"""Override any custom settings here."""

from server.settings.components.common import MIDDLEWARE
from server.settings.components.oicd import discovery_info

if discovery_info:  # use only if setup correct
    MIDDLEWARE += ("mozilla_django_oidc.middleware.SessionRefresh",)
