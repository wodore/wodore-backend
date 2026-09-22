"""Override any custom settings here."""

from server.settings.components.oidc import discovery_info

if discovery_info:  # use only if setup correct
    MIDDLEWARE += ("mozilla_django_oidc.middleware.SessionRefresh",)  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
