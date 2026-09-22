"""Conditional app/backend registrations (spec: optional-oidc, local-auth-provider).

This component is loaded LAST (after the environment file and the optional
local override) on purpose: ``split_settings`` executes every file into one
shared namespace, and the environment files re-import names from
``components.common`` (e.g. ``environments/test.py`` star-imports
``development``, which imports ``INSTALLED_APPS`` from the common module) -
appending to those names in an earlier component would be clobbered here.

The flags (``OIDC_ENABLED``, ``LOCAL_AUTH_ENABLED``) are defined by
``components/oidc.py`` and are never redefined by environment files, so they
are read directly from the shared scope (bare references, like the
``MIDDLEWARE`` guards in ``environments/*.py``).
"""

if OIDC_ENABLED:  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
    # Zitadel RP: OIDC permission backend (roles/groups -> permissions)
    AUTHENTICATION_BACKENDS += (  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
        "server.core.oidc_permission.PermissionBackend",
    )

if LOCAL_AUTH_ENABLED:  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
    # Local dev/test auth provider app (frontend talks to Django directly)
    INSTALLED_APPS += ("server.apps.local_auth",)  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
