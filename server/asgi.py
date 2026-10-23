"""
ASGI config for server project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information about this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

django_application = get_asgi_application()


async def application(scope, receive, send):
    """ASGI entrypoint that answers the lifespan protocol (Sentry 154469278).

    Django's ``ASGIHandler`` serves ``http`` scopes only and raises
    ``ValueError: Django can only handle ASGI/HTTP connections, not
    lifespan`` on anything else. The uvicorn workers (gunicorn ASGI mode)
    probe the app with a ``lifespan`` scope at every worker boot —
    lifespan is not configurable through ``uvicorn_worker`` (its
    ``CONFIG_KWARGS`` covers loop/http only), so uvicorn's default
    ``lifespan="auto"`` applies — and since the Sentry integration (#335)
    each boot surfaced that ValueError as an *unhandled* error: uvicorn
    itself only logs ``ASGI 'lifespan' protocol appears unsupported`` and
    serves on, but the SDK's ASGI patch captures the exception first.

    Answer the protocol here instead: startup and shutdown complete
    immediately. Django has no async lifespan hooks — boot work
    (migrations, sentry init, q2 clusters) runs in the entrypoint chain
    and the deployment, not inside the server process. Every other scope
    (http, and anything future) delegates to Django's handler unchanged.
    """
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        await django_application(scope, receive, send)
