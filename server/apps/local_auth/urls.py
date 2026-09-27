"""URL routes for the built-in OIDC provider.

Mounted at ``/oauth/local/`` from ``server/urls.py`` when ``OIDC_ENABLED``
is active. django-oauth-toolkit serves the OAuth2/OIDC endpoints
(discovery, authorize, token, userinfo, JWKS — its urls module carries
``app_name = "oauth2_provider"``); the compatibility ``end_session`` view
comes from this app. The issuer URL — the one the frontend is configured
with — is ``{origin}/oauth/local`` and stays the same URL the hand-rolled
provider used before this app was rebuilt on DOT.
"""

from django.urls import include, path

from server.apps.local_auth import views

# NOTE: no ``app_name`` here on purpose — DOT's urls module carries
# ``app_name = "oauth2_provider"`` and must register at the top level
# (DOT's discovery view reverses "oauth2_provider:…" without a prefix);
# declaring an app namespace here would nest it and break that reverse.

urlpatterns = [
    # DOT endpoints at the provider root (authorize/, token/, userinfo/,
    # jwks.json, .well-known/openid-configuration, …).
    path("", include("oauth2_provider.urls")),
    path("end_session", views.end_session, name="end_session"),
]
