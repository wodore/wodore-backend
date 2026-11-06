"""Async-safe replacements for third-party middleware.

Imported lazily via MIDDLEWARE string paths at handler init (apps are
ready by then) - never from settings components.
"""

import time
import typing as t
from typing import Any, override
from urllib.parse import urlencode

from mozilla_django_oidc.middleware import SessionRefresh

from django.contrib.auth.mixins import AccessMixin
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.urls import reverse


class AsyncSafeSessionRefresh(SessionRefresh):
    """SessionRefresh pinned to sync-only for the ASGI runtime.

    mozilla-django-oidc's SessionRefresh rides Django's MiddlewareMixin,
    whose self-adaptation breaks every request under ASGI (drops
    convert_exception_to_response coroutines -> plain 500s on all
    endpoints; found during the async staging rollout - sync WSGI was
    unaffected). Declaring ``async_capable = False`` makes Django bridge
    this middleware in a worker thread - the supported path for sync
    middleware.

    Verified on staging against the uvicorn runtime: all endpoints 200
    with the full Zitadel RP chain active.

    The renewal redirect is also replaced: upstream silently sends the
    browser to the provider's authorization endpoint with ``prompt=none``.
    Zitadel Login V2 violates the OIDC spec for that case when no IdP
    session exists (zitadel/zitadel#12165): instead of redirecting back
    with ``error=login_required`` it renders a dead-end JSON error page
    ("No active session found") - e.g. https://hub.stg.wodore.com/
    forwarding to auth.burgdev.ch. We route the renewal through the
    standard interactive ``/oidc/authenticate/`` entry point instead:
    with a live IdP session Zitadel completes it without any interaction
    (seamless, like ``prompt=none``), without one the user gets the real
    login page - and the original target survives via ``?next=``.

    The SCOPE is decided per resolved view, not by URL path: upstream
    checks paths in ``process_request`` (before routing), which forces a
    maintained exemption list and gets stale whenever a new surface is
    added (the hub.stg root bug: everything outside /v1, /static/ and
    /media/ silently became "refreshable"). Instead we decide in
    ``process_view`` from what Django already knows about the view:

    - admin views: ``AdminSite.admin_view()`` tags every wrapped view
      with its ``admin_site`` instance
    - CBVs using Django's access mixins (``LoginRequiredMixin``,
      ``PermissionRequiredMixin``, ``UserPassesTestMixin`` - all
      ``AccessMixin`` subclasses) expose ``view_class``

    Everything else - public pages, bearer-token API routes, and
    self-gated views that redirect to the login themselves (e.g. the
    staging demos) - is out of scope. Function decorators
    (``login_required``/``staff_member_required``) leave no standard
    marker and are not detected; such views run their own interactive
    redirect-to-login, which does not need the silent renewal.
    ``OIDC_EXEMPT_URLS`` stays available as an explicit escape hatch.
    """

    async_capable = False

    @override
    def process_request(self, request: HttpRequest) -> None:
        # Neutralized: upstream decides by PATH here, before routing. We
        # decide by VIEW in process_view instead (see class docstring).
        return None

    @staticmethod
    def _view_uses_login_session(view_func: t.Callable[..., Any]) -> bool:
        """Whether the resolved view renders for an authenticated
        Django session (the only surface an id_token renewal serves)."""
        # AdminSite.admin_view() tags every admin view:
        if hasattr(view_func, "admin_site"):
            return True
        # Access-mixin CBVs (LoginRequired/PermissionRequired/UserPassesTest):
        view_class = getattr(view_func, "view_class", None)
        return isinstance(view_class, type) and issubclass(view_class, AccessMixin)

    def process_view(
        self,
        request: HttpRequest,
        view_func: t.Callable[..., Any],
        view_args: list[Any],
        view_kwargs: dict[str, Any],
    ) -> HttpResponse | None:
        if request.method != "GET" or not self._view_uses_login_session(view_func):
            return None
        # Authenticated OIDC session + not an explicitly exempt path
        # (the mozilla authenticate/callback/logout routes are always
        # exempt here - that is also our redirect-loop protection).
        if not self.is_refreshable_url(request):
            return None

        expiration = request.session.get("oidc_id_token_expiration", 0)
        if expiration > time.time():
            # The id_token is still valid, so we don't have to do anything.
            return None

        # The id_token has expired: re-authenticate through the standard
        # login entry point (see class docstring - never a prompt=none
        # authorize request). The view sanitizes ``next`` itself.
        redirect_url = "{url}?{query}".format(
            url=reverse("oidc_authentication_init"),
            query=urlencode({"next": request.get_full_path()}),
        )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            # Same XHR contract as upstream SessionRefresh: a 403 carrying
            # the refresh URL so client-side code can navigate itself.
            response = JsonResponse({"refresh_url": redirect_url}, status=403)
            response["refresh_url"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)
