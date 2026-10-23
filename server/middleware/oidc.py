"""Async-safe replacements for third-party middleware.

Imported lazily via MIDDLEWARE string paths at handler init (apps are
ready by then) - never from settings components.
"""

import time
from urllib.parse import urlencode

from mozilla_django_oidc.middleware import SessionRefresh

from django.http import HttpResponseRedirect, JsonResponse
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
    """

    async_capable = False

    def process_request(self, request):
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
