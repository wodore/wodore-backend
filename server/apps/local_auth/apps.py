"""Built-in OIDC provider app (spec: oidc-provider).

django-oauth-toolkit (DOT) is the OAuth2/OIDC machinery, django-allauth the
account system behind it; this app is the glue mounted at ``/oauth/local/``:

- DOT's endpoints (discovery, authorize + PKCE, token, userinfo, JWKS)
- the ``ProviderOAuth2Validator`` claims hook (legacy Zitadel-shaped roles
  map + plain ``roles`` list, built from Django groups)
- the ``end_session`` compatibility view
- the ``local_auth_users`` fixture command (users, groups, OAuth clients)
- allauth template overrides (popup-friendly, mobile-first)

Login happens through allauth (``/accounts/login/``); DOT's authorize view
redirects unauthenticated users there and back. Token renewal uses DOT
refresh tokens (rotation + reuse protection enabled in settings).
"""

from django.apps import AppConfig


class LocalAuthConfig(AppConfig):
    name = "server.apps.local_auth"
    verbose_name = "Built-in OIDC Provider"
    default_auto_field = "django.db.models.BigAutoField"
