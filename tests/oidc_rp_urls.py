"""Minimal URLconf mirroring the Zitadel-RP surface of ``server.urls``:
mozilla-django-oidc endpoints, a public root and - for the
SessionRefresh scope tests - a REAL Django admin site (hermetic: its
own AdminSite instance, so the global unfold site and its registered
models stay out) plus a LoginRequiredMixin CBV mounted on a public-ish
path, proving the view-based scope detection.

The real ``server.urls`` only mounts ``mozilla_django_oidc.urls`` when
``AUTH_PROVIDER=zitadel``, which the test environment does not use.
"""

from django.contrib import admin
from django.contrib.auth import mixins
from django.http import HttpRequest, HttpResponse
from django.urls import include, path
from django.views import View


def _ok(request: HttpRequest):
    return HttpResponse("ok")


class _GatedView(mixins.LoginRequiredMixin, View):
    def get(self, request: HttpRequest):
        return HttpResponse("gated")


class _DemosAdminSite(admin.AdminSite):
    """Staging-demos stand-in: self-gated view, NOT admin-detectable."""


demo_admin = _DemosAdminSite(name="demos")


def _demo_view(request: HttpRequest):
    """Self-gated demo: authenticated superusers see the page, others
    are redirected to the login view (mirrors the demos app)."""
    if request.user.is_authenticated and request.user.is_superuser:  # type: ignore  # dynamic attr: plugin-less inference gap
        return HttpResponse("demo")
    return _redirect_to_login(request)


urlpatterns = [
    path("", _ok, name="index"),
    # Access-mixin CBV outside /admin: must be auto-detected by the
    # middleware regardless of its path.
    path("manager/gated/", _GatedView.as_view()),
    # Self-gated demo view (mirrors server.apps.demos.views.mapcompare:
    # checks permissions in-view and redirects to the login itself).
    path("demos/mapcompare/", _demo_view),
    # A real admin site: its views carry the AdminSite.admin_view marker.
    path("admin/", demo_admin.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
]


def _redirect_to_login(request: HttpRequest):
    from django.contrib.auth.views import redirect_to_login

    return redirect_to_login(request.get_full_path())
