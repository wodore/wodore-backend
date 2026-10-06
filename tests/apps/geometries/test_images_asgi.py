"""ASGI-path integration tests for the geo image endpoints.

Staging serves the API over ASGI (gunicorn + uvicorn workers). There,
sync controllers execute inside asgiref's sync/async bridging machinery,
and the historical ``asyncio.run(fetch_images_from_providers(...))``
bridge made every nested ``sync_to_async`` in the provider stack fail
(asgiref's CurrentThreadExecutor self-submit guard / executor deadlock)
— the error was swallowed and the endpoints answered (and cached!) empty
FeatureCollections. The Django test client exercises only the WSGI
path, so the suite never noticed.

These tests drive the real ASGI application — full middleware chain,
sync views dispatched through ``sync_to_async`` — with every registered
provider's ``fetch`` stubbed to return images, and assert the endpoints
actually return features.
"""

import asyncio
import threading
import time

import httpx
import pytest

from django.core.asgi import get_asgi_application
from django.test import override_settings

from server.apps.geometries import (
    api_images,  # noqa: F401 -- imports register the providers
)
from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.models import GeoPlace
from server.apps.geometries.providers import provider_registry
from server.apps.geometries.providers.base import ImageResult
from server.apps.huts.models import Hut

pytestmark = [pytest.mark.django_db]

_IMAGOR_TEST_IMAGE = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/Test_1920.jpg"
)


@pytest.fixture(scope="module")
def asgi_app():
    """The real ASGI application (ASGIHandler + middleware chain)."""
    return get_asgi_application()


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Private locmem response cache per test (no database cache leakage)."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    cache = LocMemCache(f"test-{uuid4().hex}", {})
    monkeypatch.setattr(irc, "_cache", lambda: cache)


@pytest.fixture(autouse=True)
def _cleanup_committed_writes(django_db_blocker):
    """Remove rows the ASGI view threads COMMIT behind pytest-django's back.

    The sync views run on asgiref executor threads with their own
    autocommit connections, outside the per-test transaction pytest-django
    rolls back. The license auto-create in ``post_process_images``
    (``_get_license_info``: missing license → ``License.objects.create``
    with the model's ``no_publication=True`` default) therefore leaks a
    committed row into the reused test database — and any later session's
    pinning tests exclude those pins. Delete exactly that auto-created row
    (review_status="new") after each test, on a throwaway connection so
    the delete itself commits instead of joining the rolled-back
    transaction; seed licenses are untouched.
    """
    yield
    from django.conf import settings
    from django.db.utils import ConnectionHandler

    with django_db_blocker.unblock():
        conn = ConnectionHandler(settings.DATABASES)["default"]
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM licenses_license "
                    "WHERE slug = %s AND review_status = %s AND no_publication",
                    ["cc-by-sa-4-0", "new"],
                )
        finally:
            conn.close()


def _stub_result(provider_source: str, index: int) -> ImageResult:
    from django.contrib.gis.geos import Point

    return ImageResult(
        provider=provider_source,
        source_id=f"File:{provider_source}-{index}.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:Test.jpg",
        image_type="flat",
        captured_at=None,
        location=Point(7.5, 46.5),
        distance_m=42.0,
        license_slug="cc-by-sa-4-0",
        attribution="Test Author, CC BY-SA",
        author="Test Author",
        author_url=None,
        url_large=_IMAGOR_TEST_IMAGE,
        width=1920,
        height=1080,
        score=80,
    )


@pytest.fixture(autouse=True)
def _stub_providers(monkeypatch):
    """Every registered provider answers 1–2 images without network.

    Only the provider ``fetch`` methods are stubbed: the endpoints still
    run the real aggregation stack (``run_async`` bridging, place schema
    conversion with its nested ``sync_to_async``, dedupe, post-process).
    """

    async def _fetch(self, places, lat, lon, radius, limit=100, update_cache=False):
        # 1–2 images per provider, dimensions large enough to survive
        # post_process_images' minimum-size filter.
        return [_stub_result(self.source, 1), _stub_result(self.source, 2)][
            : 1 + (self.priority % 2)
        ]

    stubbed = []
    for provider in provider_registry.get_all_providers():
        monkeypatch.setattr(provider, "fetch", _fetch.__get__(provider))
        stubbed.append(provider.source)
    # Providers register on the api_images import — a missing one means
    # the URLconf was never loaded and the request would hit the REAL
    # providers (network!) instead of the stubs.
    assert stubbed, "no image providers registered — stubs not applied"


def _asgi_get(app, url: str) -> httpx.Response:
    """Drive one GET through the real ASGI stack (event loop + asgiref
    bridging, sync views dispatched via sync_to_async like under uvicorn)."""

    async def _do() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.get(url)

    return asyncio.run(_do())


@pytest.fixture
def hut(seed_data):
    hut = Hut.objects.filter(
        is_active=True, is_public=True, location__isnull=False
    ).first()
    assert hut is not None, "seed data provides no public hut"
    return hut


@pytest.fixture
def place(seed_data):
    place = GeoPlace.objects.filter(
        is_active=True, is_public=True, location__isnull=False
    ).first()
    assert place is not None, "seed data provides no public place"
    return place


class TestImagesEndpointsUnderASGI:
    """All three image endpoints must return features when served over
    ASGI — the failure mode that emptied them on staging (swallowed
    bridging errors → empty responses) must not recur."""

    def test_nearby_images_return_features(self, asgi_app, hut):
        url = f"/v1/geo/images/nearby?lat={hut.location.y}&lon={hut.location.x}&radius=50&lang=en&limit=20"
        response = _asgi_get(asgi_app, url)
        assert response.status_code == 200
        features = response.json()["features"]
        assert len(features) > 0
        assert not features[0]["properties"].get("is_fallback")

    def test_place_images_return_features(self, asgi_app, place):
        # sources=wikicommons keeps the request off the pinning
        # write-through (the ASGI view thread's connection commits for
        # real, outside pytest-django's test transaction).
        url = f"/v1/geo/images/place/{place.slug}?radius=50&sources=wikicommons&lang=en&limit=20"
        response = _asgi_get(asgi_app, url)
        assert response.status_code == 200
        features = response.json()["features"]
        assert len(features) > 0
        assert not features[0]["properties"].get("is_fallback")

    def test_hut_images_return_features(self, asgi_app, hut):
        url = f"/v1/geo/images/hut/{hut.slug}?radius=50&sources=wikicommons&lang=en&limit=20"
        response = _asgi_get(asgi_app, url)
        assert response.status_code == 200
        features = response.json()["features"]
        assert len(features) > 0
        assert not features[0]["properties"].get("is_fallback")


class TestFanoutBudget:
    """P0 2026-10-05: one straggling provider must not hold the request.

    The overall fan-out budget cancels providers still running at the
    deadline and serves the fast providers' partial results (which the
    response-cache path then caches as usual) — bounded latency instead
    of a 30-60s request that upstream clients abort mid-flight.
    """

    def test_slow_provider_serves_partial_results_within_budget(
        self, asgi_app, hut, monkeypatch
    ):
        from structlog.testing import capture_logs

        slow = provider_registry.get_provider("wikicommons")

        async def _slow_fetch(
            self, places, lat, lon, radius, limit=100, update_cache=False
        ):
            await asyncio.sleep(30.0)  # far beyond the 0.3s budget
            return [_stub_result(self.source, 99)]

        monkeypatch.setattr(slow, "fetch", _slow_fetch.__get__(slow))

        url = f"/v1/geo/images/nearby?lat={hut.location.y}&lon={hut.location.x}&radius=50&lang=en&limit=20"
        with (
            override_settings(IMAGES_FANOUT_BUDGET_SECONDS=0.3),
            capture_logs() as logs,
        ):
            started = time.monotonic()
            response = _asgi_get(asgi_app, url)
            elapsed = time.monotonic() - started

        assert response.status_code == 200
        features = response.json()["features"]
        assert features, "fast providers' partial results must be served"
        assert all(
            "wikicommons" not in f["properties"]["source_id"] for f in features
        ), "straggler's results must not appear"
        assert elapsed < 5.0, f"request must respect the budget (took {elapsed:.1f}s)"
        stragglers = [
            e
            for e in logs
            if "budget" in e.get("event", "") and e.get("provider") == "wikicommons"
        ]
        assert stragglers, "timed-out provider must be logged, not raised"

    def test_explicit_budget_overrides_setting(self, monkeypatch):
        """The budget parameter wins over the setting (pin-command path).

        The setting stays at its 10s default here; only the explicit 0.3s
        budget can explain finishing fast with the other providers'
        partial results — geoimages_pin passes this parameter through
        ``sync_place_images`` so background sweeps can wait longer.
        """
        from structlog.testing import capture_logs

        from server.apps.geometries.providers import (
            fetch_images_from_providers,
            run_async,
        )

        slow = provider_registry.get_provider("wikicommons")

        async def _slow_fetch(
            self, places, lat, lon, radius, limit=100, update_cache=False
        ):
            await asyncio.sleep(30.0)  # far beyond the 0.3s explicit budget
            return [_stub_result(self.source, 99)]

        monkeypatch.setattr(slow, "fetch", _slow_fetch.__get__(slow))

        with capture_logs() as logs:
            started = time.monotonic()
            results = run_async(
                fetch_images_from_providers,
                geoplaces=[],
                huts=[],
                lat=46.5,
                lon=7.5,
                radius=50.0,
                budget=0.3,
            )
            elapsed = time.monotonic() - started

        assert results, "fast providers' partial results must be returned"
        assert all(r.provider != "wikicommons" for r in results)
        assert elapsed < 5.0, f"explicit budget must bind (took {elapsed:.1f}s)"
        assert any(
            "budget" in e.get("event", "") and e.get("provider") == "wikicommons"
            for e in logs
        )


class TestCancelledRequestConnectionHygiene:
    """P0 2026-10-05: a cancelled request must not strand a pool checkout.

    Reproduces the abort path from the incident: the request is driven
    through the real ASGI app (full middleware chain) with one provider
    sleeping far beyond a short deadline, then the request task itself is
    cancelled — as when Traefik or the client gives up. The CancelledError
    travels the same asgiref bridge as on staging.

    Observability is the hard part of integration-level cancellation: the
    leaked connection lives in the detached sync view thread's
    asgiref-local ``ConnectionHandler``, which the test thread cannot
    enumerate. So the test spies on ``connections.all(initialized_only=...)``
    — what ``run_async``'s cleanup enumerates — and forces each connection's
    ``close_at`` to 0, simulating the staging pool setup (``CONN_MAX_AGE=0``
    makes every connection immediately obsolete, so the cleanup must close
    it — with the psycopg pool that means checking it back in). It then
    asserts the cleanup ran on the view thread, saw the request's open
    connection, and actually closed it.
    """

    def test_cancelled_request_releases_view_thread_connections(
        self, asgi_app, hut, monkeypatch
    ):
        import django.db

        slow = provider_registry.get_provider("wikicommons")
        fetch_started = threading.Event()

        async def _slow_fetch(
            self, places, lat, lon, radius, limit=100, update_cache=False
        ):
            fetch_started.set()
            await asyncio.sleep(30.0)
            return []

        monkeypatch.setattr(slow, "fetch", _slow_fetch.__get__(slow))

        cleanup_calls: list[dict] = []
        cleanup_started = threading.Event()
        connections = django.db.connections
        real_all = connections.all

        def _spied_all(initialized_only=False):
            conns = real_all(initialized_only=initialized_only)
            if initialized_only and conns:
                cleanup_calls.append(
                    {
                        "thread": threading.current_thread().name,
                        "conns": list(conns),
                        "open_before": [c.connection is not None for c in conns],
                    }
                )
                for conn in conns:
                    # Staging semantics: CONN_MAX_AGE=0 → always obsolete.
                    conn.close_at = 0.0
                cleanup_started.set()
            return conns

        monkeypatch.setattr(connections, "all", _spied_all)

        async def _aborted_get() -> None:
            transport = httpx.ASGITransport(app=asgi_app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                url = f"/v1/geo/images/nearby?lat={hut.location.y}&lon={hut.location.x}&radius=50&lang=en&limit=20"
                request_task = asyncio.create_task(client.get(url))
                # Wait until the fan-out is actually inside the slow
                # provider, then abort the request task — a deterministic
                # mid-flight cancellation, like an upstream proxy abort.
                for _ in range(500):
                    if fetch_started.is_set():
                        break
                    await asyncio.sleep(0.02)
                assert fetch_started.is_set(), "provider fetch never started"
                request_task.cancel()
                # The abort unwinds through the asgiref bridge; whatever
                # escapes the cancelled request itself is not what this
                # test asserts about.
                await asyncio.gather(request_task, return_exceptions=True)

        asyncio.run(_aborted_get())

        assert cleanup_started.wait(timeout=10.0), (
            "run_async connection cleanup never ran after request cancellation"
        )
        view_thread_calls = [
            c for c in cleanup_calls if c["thread"] != threading.main_thread().name
        ]
        assert view_thread_calls, "cleanup must run on the sync view thread"
        released = [
            conn
            for call in view_thread_calls
            for conn, was_open in zip(call["conns"], call["open_before"])
            if was_open and not conn.in_atomic_block
        ]
        assert released, (
            "the aborted request held an open DB connection at cleanup time"
        )
        # The cleanup must actually close them (staging: check back into
        # the psycopg pool instead of leaking the checkout).
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if all(conn.connection is None for conn in released):
                break
            time.sleep(0.05)
        assert all(conn.connection is None for conn in released), (
            "cancelled request's DB connections were not closed"
        )
