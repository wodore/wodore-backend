"""Local dev/test auth provider (spec: local-auth-provider).

A minimal built-in OIDC provider so the frontend (and integration tests) can
authenticate directly against Django when Zitadel is not available. It speaks
just enough OIDC for ``oidc-client-ts`` with these settings:

- discovery document
- authorization code flow with PKCE (S256), popup sign-in and ``prompt=none``
  silent renew backed by the Django session
- token endpoint (code + PKCE, plus a dev/test password grant)
- userinfo with Zitadel-shaped role claims (built from Django groups)
- JWKS and end-session endpoints

The app is only ever mounted in DEBUG/test environments - the settings loader
(``server.settings.components.oidc``) refuses ``LOCAL_AUTH_ENABLED=true``
anywhere else. Nothing here is hardened for production exposure on purpose.
"""

from django.apps import AppConfig


class LocalAuthConfig(AppConfig):
    name = "server.apps.local_auth"
    verbose_name = "Local Auth (dev/test)"
    default_auto_field = "django.db.models.BigAutoField"
