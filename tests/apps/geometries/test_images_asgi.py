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

import httpx
import pytest

from django.core.asgi import get_asgi_application

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


class TestConcurrentBridgeRequests:
    """The 2026-10-05 staging wedge (pool exhaustion → readiness 503) started
    with concurrent geo requests crossing the asgiref sync/async bridge.

    Requests are driven through the real ASGI stack concurrently; the
    providers are stubbed (fast), so this is a routing/deadlock canary for
    the bridge machinery (``run_async`` → ``async_to_sync`` onto the main
    loop → nested thread-sensitive ``sync_to_async``), not a load test.
    A hard hang here is exactly the incident's wedge shape.
    """

    @staticmethod
    def _concurrent_get(app, urls: list[str]) -> list[httpx.Response]:
        async def _do() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver", timeout=30
            ) as client:
                gathered = await asyncio.wait_for(
                    asyncio.gather(*[client.get(url) for url in urls]), timeout=60
                )
                return list(gathered)

        return asyncio.run(_do())

    def test_concurrent_mixed_requests_complete(self, asgi_app, hut, place):
        """8 concurrent requests across all three endpoints must all answer."""
        urls = [
            f"/v1/geo/images/nearby?lat={hut.location.y}&lon={hut.location.x}&radius=50&lang=en&limit=20",
            f"/v1/geo/images/place/{place.slug}?radius=50&sources=wikicommons&lang=en&limit=20",
            f"/v1/geo/images/hut/{hut.slug}?radius=50&sources=wikicommons&lang=en&limit=20",
        ] * 3  # 9 requests, mixed endpoints, overlapping bridges
        responses = self._concurrent_get(asgi_app, urls)
        assert len(responses) == len(urls)
        for response in responses:
            assert response.status_code == 200
