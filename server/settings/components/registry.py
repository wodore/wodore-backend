"""Conditional app/backend/middleware registrations
(specs: optional-oidc, oidc-provider, account-management).

This component is loaded LAST (after the environment file and the optional
local override) on purpose: ``split_settings`` executes every file into one
shared namespace, and the environment files re-import names from
``components.common`` (e.g. ``environments/test.py`` star-imports
``development``, which imports ``INSTALLED_APPS`` from the common module) -
appending to those names in an earlier component would be clobbered here.

The flags (``OIDC_ENABLED``) are defined by ``components/oidc.py`` and are
never redefined by environment files, so they are read directly from the
shared scope (bare references).
"""

if OIDC_ENABLED:  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
    # Built-in OIDC provider + account management.
    # server.apps.local_auth is listed FIRST: its template overrides
    # (allauth account templates) must be found before allauth's own.
    INSTALLED_APPS += (  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        "server.apps.local_auth",
        "oauth2_provider",
        "allauth",
        "allauth.account",
        "allauth.mfa",
    )
    if "django.contrib.sites" not in INSTALLED_APPS:
        INSTALLED_APPS += ("django.contrib.sites",)
    SITE_ID = 1

    MIDDLEWARE += (  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        "allauth.account.middleware.AccountMiddleware",
    )

    AUTHENTICATION_BACKENDS += (  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        "allauth.account.auth_backends.AuthenticationBackend",
    )
