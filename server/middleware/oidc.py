"""Async-safe replacements for third-party middleware.

Imported lazily via MIDDLEWARE string paths at handler init (apps are
ready by then) - never from settings components.
"""

from mozilla_django_oidc.middleware import SessionRefresh


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
    """

    async_capable = False
