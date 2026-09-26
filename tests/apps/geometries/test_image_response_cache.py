"""Tests for the geo-images response cache (spec: image-response-cache).

Unit tests cover the helper module; endpoint tests drive the ninja router
with stubbed provider fetches to verify caching, parameter separation,
stale-fallback, forced refresh, and invalidation.
"""

import pytest
from ninja.testing import TestClient

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.api_images import router
from server.apps.geometries.image_response_cache import (
    center_ident,
    get_response,
    invalidate_for_hut,
    normalize_sources,
    response_key,
    set_response,
)
from server.apps.geometries.schemas import ImageCollectionResponse, ImageMetadataSchema


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Give every test a private locmem cache.

    Overriding ``CACHES`` via settings is unreliable here (the cache handler
    may keep serving the database backend and leak entries across runs), so
    patch the module's cache resolver to a fresh in-memory backend instead.
    """
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    # LocMemCache shares storage per (name, location) — unique name per test,
    # single instance so writes and reads meet.
    cache = LocMemCache(f"test-{uuid4().hex}", {})
    monkeypatch.setattr(irc, "_cache", lambda: cache)


def _sample_response(total: int = 0) -> ImageCollectionResponse:
    return ImageCollectionResponse(
        type="FeatureCollection",
        features=[],
        metadata=ImageMetadataSchema(
            total=total,
            sources_queried=["wodore"],
            query_radius_m=50.0,
            center={"lat": 46.5, "lon": 7.5},
            geoplaces_found=0,
            huts_found=1,
        ),
    )


class TestResponseCacheHelper:
    def test_roundtrip_fresh(self):
        key = response_key("hut", "s", radius=50.0, sources=None, lang="en", limit=10)
        set_response(key, _sample_response(total=3))
        cached, fresh = get_response(key)
        assert fresh is True
        assert cached is not None
        assert cached.metadata.total == 3

    def test_stale_after_fresh_window(self, monkeypatch):
        monkeypatch.setattr(irc, "fresh_seconds", lambda: -1)
        key = response_key("hut", "s", radius=50.0, sources=None, lang="en", limit=10)
        set_response(key, _sample_response(total=1))
        cached, fresh = get_response(key)
        assert fresh is False
        assert cached is not None  # still retrievable for stale fallback

    def test_storage_expiry_returns_nothing(self, settings):
        settings.IMAGE_RESPONSE_CACHE_STALE_SECONDS = 0
        key = response_key("hut", "s", radius=50.0, sources=None, lang="en", limit=10)
        set_response(key, _sample_response())
        cached, fresh = get_response(key)
        assert cached is None
        assert fresh is False

    def test_version_bump_invalidates(self):
        key_1 = response_key("hut", "s", radius=50.0, sources=None, lang="en", limit=10)
        set_response(key_1, _sample_response())
        invalidate_for_hut("s")
        key_2 = response_key("hut", "s", radius=50.0, sources=None, lang="en", limit=10)
        assert key_1 != key_2
        cached, _fresh = get_response(key_2)
        assert cached is None  # new version → old entries unreachable

    def test_normalize_sources(self):
        assert normalize_sources("b,a") == normalize_sources("a,b")
        assert normalize_sources("a, a,b") == "a,b"
        assert normalize_sources(" b ,,a") == "a,b"
        assert normalize_sources(None) == "all"
        assert normalize_sources("") == "all"

    def test_center_ident_rounding(self):
        assert center_ident(46.123456, 7.9) == center_ident(46.123461, 7.9)
        assert center_ident(46.123456, 7.9) != center_ident(46.124, 7.9)


class _FetchStub:
    """Stands in for fetch_images_for_place / fetch_images_from_providers."""

    def __init__(self, returns_tuple: bool = True):
        self.calls = 0
        self.exc: Exception | None = None
        self.returns_tuple = returns_tuple
        self.place_info = {"location": {"lat": 46.5, "lon": 7.5}}

    async def __call__(self, **kwargs):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        if self.returns_tuple:
            return [], self.place_info
        return []


@pytest.mark.django_db
class TestEndpointCaching:
    @pytest.fixture
    def client(self):
        return TestClient(router)

    @pytest.fixture
    def hut_slug(self, seed_data):
        from server.apps.huts.models import Hut

        slug = (
            Hut.objects.filter(is_active=True, is_public=True)
            .values_list("slug", flat=True)
            .first()
        )
        assert slug, "seed data provides no public hut"
        return slug

    @pytest.fixture
    def fetch(self, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub()
        monkeypatch.setattr(api_images, "fetch_images_for_place", stub)
        return stub

    def test_second_request_hits_cache(self, client, hut_slug, fetch):
        url = f"/hut/{hut_slug}?radius=50&lang=en&limit=10"
        first = client.get(url)
        second = client.get(url)
        assert first.status_code == 200
        assert second.status_code == 200
        assert fetch.calls == 1  # second response served from cache
        assert second.json() == first.json()

    def test_parameters_split_cache(self, client, hut_slug, fetch):
        client.get(f"/hut/{hut_slug}?radius=50&lang=en&limit=10")
        client.get(f"/hut/{hut_slug}?radius=50&lang=fr&limit=10")
        client.get(f"/hut/{hut_slug}?radius=100&lang=en&limit=10")
        assert fetch.calls == 3

    def test_update_cache_bypasses_and_resets(self, client, hut_slug, fetch):
        url = f"/hut/{hut_slug}?radius=50&lang=en&limit=10"
        client.get(url)
        client.get(f"{url}&update_cache=true")
        assert fetch.calls == 2  # forced refresh recomputed
        client.get(url)
        assert fetch.calls == 2  # fresh again → served from cache

    def test_stale_fallback_on_failure(self, client, hut_slug, fetch, monkeypatch):
        monkeypatch.setattr(irc, "fresh_seconds", lambda: -1)
        url = f"/hut/{hut_slug}?radius=50&lang=en&limit=10"
        first = client.get(url)
        assert first.status_code == 200

        fetch.exc = RuntimeError("provider down")
        second = client.get(url)  # recompute fails → stale fallback
        assert second.status_code == 200
        assert second.json() == first.json()
        assert fetch.calls == 2

    def test_failure_without_cache_raises(self, client, hut_slug, fetch, monkeypatch):
        monkeypatch.setattr(irc, "fresh_seconds", lambda: -1)
        fetch.exc = RuntimeError("provider down")
        with pytest.raises(RuntimeError, match="provider down"):
            client.get(f"/hut/{hut_slug}?radius=50&lang=en&limit=10")

    def test_invalidate_forces_recompute(self, client, hut_slug, fetch):
        url = f"/hut/{hut_slug}?radius=50&lang=en&limit=10"
        client.get(url)
        invalidate_for_hut(hut_slug)
        client.get(url)
        assert fetch.calls == 2

    def test_nearby_cached(self, seed_data, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub(returns_tuple=False)
        monkeypatch.setattr(api_images, "fetch_images_from_providers", stub)
        client = TestClient(router)
        url = "/nearby?lat=46.5&lon=7.5&radius=100&lang=en&limit=10"
        assert client.get(url).status_code == 200
        assert client.get(url).status_code == 200
        assert stub.calls == 1
