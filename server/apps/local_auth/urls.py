"""URL routes for the local dev/test auth provider.

Mounted at ``/oauth/local/`` from ``server/urls.py`` when
``LOCAL_AUTH_ENABLED`` is active (DEBUG/test only).
"""

from django.urls import path

from server.apps.local_auth import views

app_name = "local_auth"

urlpatterns = [
    path(
        ".well-known/openid-configuration",
        views.discovery,
        name="discovery",
    ),
    path("authorize", views.authorize, name="authorize"),
    path("token", views.token, name="token"),
    path("userinfo", views.userinfo, name="userinfo"),
    path("jwks", views.jwks, name="jwks"),
    path("end_session", views.end_session, name="end_session"),
]
