"""The ASGI entrypoint answers the lifespan protocol (Sentry 154469278).

uvicorn workers (gunicorn ASGI mode, lifespan defaulting to "auto" —
``uvicorn_worker`` exposes no knob for it) probe the application with a
``lifespan`` scope on every worker boot; Django's ASGIHandler raises
ValueError on non-http scopes, which the Sentry SDK's ASGI patch reports
as an unhandled error per boot. ``server.asgi:application`` answers the
protocol itself — these tests pin that contract, plus the unchanged
pass-through of every other scope to Django's handler.
"""

import asyncio

from server.asgi import application

_LIFESPAN_SCOPE = {
    "type": "lifespan",
    "asgi": {"version": "3.0", "spec_version": "2.0"},
    "state": {},
}


def _drive_lifespan(messages: list[dict]) -> list[dict]:
    """Run one lifespan session the way uvicorn's LifespanOn does:
    queued incoming messages, recorded outgoing replies."""
    inbox: asyncio.Queue = asyncio.Queue()
    for message in messages:
        inbox.put_nowait(message)
    replies: list[dict] = []

    async def receive() -> dict:
        return await inbox.get()

    async def send(message: dict) -> None:
        replies.append(message)

    asyncio.run(application(_LIFESPAN_SCOPE, receive, send))
    return replies


def test_lifespan_session_completes_both_phases():
    """A full session answers startup and shutdown in order."""
    replies = _drive_lifespan(
        [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    )
    assert replies == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]


def test_lifespan_shutdown_without_startup():
    """Servers may skip startup probing; shutdown alone still completes."""
    replies = _drive_lifespan([{"type": "lifespan.shutdown"}])
    assert replies == [{"type": "lifespan.shutdown.complete"}]


def test_non_lifespan_scopes_delegate_to_django(monkeypatch):
    """http (and any other) scopes still reach Django's ASGIHandler."""

    async def django_application(scope, receive, send):  # pragma: no cover
        assert scope["type"] == "http"
        assert receive is None and send is None  # passed through verbatim

    monkeypatch.setattr("server.asgi.django_application", django_application)

    scope = {"type": "http", "path": "/"}
    asyncio.run(application(scope, None, None))
