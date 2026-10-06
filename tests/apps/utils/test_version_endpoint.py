"""HTTP-level tests for ``GET /v1/version``.

The discovery endpoint reports build/runtime/API version information
and must stay reachable: the frontend's api-version store reads
supported versions and lifecycle status from it. Regression tests for
the staging 500: the alpine production image baked an unparseable
BusyBox ``date`` artifact into ``BUILD_TIMESTAMP`` (its ``date`` does
not support ``%N``) and ``datetime.fromisoformat`` raised ValueError
in the handler.
"""

import datetime

import pytest

from server.apps.apiversions import registry

pytestmark = [pytest.mark.django_db]

# What busybox date -u +%Y-%m-%dT%H:%M:%S.%6NZ actually emitted in the
# alpine production image (literal fallback for the unsupported %N).
BUSYBOX_GARBAGE = "2026-10-06T06:57:53.   %6NZ"


def test_version_endpoint_returns_200(client):
    """Happy path: the discovery endpoint answers with all sections."""
    response = client.get("/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert body["api"]["current"] == registry.current_version()
    assert body["api"]["default"] == registry.default_version()
    supported = {entry["version"] for entry in body["api"]["supported"]}
    assert registry.versions()[0] in supported
    assert body["environment"] in {"development", "test", "staging", "production"}


def test_version_endpoint_tolerates_unparseable_build_timestamp(client, monkeypatch):
    """A garbage BUILD_TIMESTAMP must not turn the endpoint into a 500.

    Staging bug: the entrypoint exported the BusyBox date artifact
    (``2026-10-06T06:57:53.   %6NZ``); ``fromisoformat`` raised
    ValueError and the endpoint answered 500 for pinned and unpinned
    clients alike. Build metadata is best-effort — the discovery
    endpoint must keep serving the API version registry.
    """
    monkeypatch.setattr("server.apps.utils.api.BUILD_TIMESTAMP", BUSYBOX_GARBAGE)

    response = client.get("/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert body["hash"]
    assert body["api"]["current"] == registry.current_version()
    # The fallback timestamp is a real, parseable datetime.
    datetime.datetime.fromisoformat(body["timestamp"])


def test_version_endpoint_parses_utc_build_timestamp(client, monkeypatch):
    """Z-suffixed (or offset) build timestamps parse and round-trip.

    The debian/ubuntu images emit GNU date output with a trailing Z;
    the fixed Dockerfiles emit RFC3339 with a +00:00 offset. Both are
    valid fromisoformat input and must reach the client as timestamps.
    """
    monkeypatch.setattr(
        "server.apps.utils.api.BUILD_TIMESTAMP",
        "2026-10-06T06:57:53.123456+00:00",
    )

    response = client.get("/v1/version")

    assert response.status_code == 200
    body = response.json()
    parsed = datetime.datetime.fromisoformat(body["timestamp"])
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 6
