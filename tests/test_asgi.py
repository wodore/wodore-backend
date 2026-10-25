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
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

import pytest

from server.asgi import application

_LIFESPAN_SCOPE: dict[str, Any] = {
    "type": "lifespan",
    "asgi": {"version": "3.0", "spec_version": "2.0"},
    "state": {},
}


def _drive_lifespan(
    messages: list[dict[str, Any]],
) -> list[Mapping[str, Any]]:
    """Run one lifespan session the way uvicorn's LifespanOn does:
    queued incoming messages, recorded outgoing replies."""
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for message in messages:
        inbox.put_nowait(message)
    replies: list[Mapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return await inbox.get()

    async def send(message: Mapping[str, Any]) -> None:
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


def test_non_lifespan_scopes_delegate_to_django(monkeypatch: pytest.MonkeyPatch):
    """http (and any other) scopes still reach Django's ASGIHandler."""

    async def django_application(  # pragma: no cover
        scope: dict[str, Any], receive: object, send: object
    ):
        assert scope["type"] == "http"
        assert receive is None and send is None  # passed through verbatim

    monkeypatch.setattr("server.asgi.django_application", django_application)

    scope = {"type": "http", "path": "/"}
    # None receive/send pin the verbatim passthrough (never called for http scopes).
    asyncio.run(
        application(
            scope,
            cast("Callable[[], Awaitable[Mapping[str, Any]]]", None),
            cast("Callable[[Mapping[str, Any]], Awaitable[None]]", None),
        )
    )
