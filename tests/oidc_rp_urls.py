"""Minimal URLconf mirroring the Zitadel-RP surface of ``server.urls``:
mozilla-django-oidc endpoints, an admin path and a public root.

Used by the SessionRefresh tests (``tests/test_oidc_session_refresh.py``):
the real ``server.urls`` only mounts ``mozilla_django_oidc.urls`` when
``AUTH_PROVIDER=zitadel``, which the test environment does not use.
"""

from django.http import HttpResponse
from django.urls import include, path


def _ok(request):
    return HttpResponse("ok")


urlpatterns = [
    path("", _ok, name="index"),
    path("admin/", _ok),
    path("oidc/", include("mozilla_django_oidc.urls")),
]
