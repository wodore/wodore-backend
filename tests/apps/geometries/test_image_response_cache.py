"""Tests for the geo-images response cache (spec: image-response-cache).
Unit tests cover the helper module; endpoint tests drive the ninja router
with stubbed provider fetches to verify caching, parameter separation,
stale-fallback, forced refresh, and invalidation.
"""

import pytest

from tests.helpers import PrefixedClient as TestClient

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.image_response_cache import (
    center_ident,
    get_response,
    invalidate_for_hut,
    normalize_sources,
    response_key,
    set_response,
)
from server.apps.geometries.schemas import (
    ImageCenterSchema,
    ImageCollectionResponse,
    ImageMetadataSchema,
)


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
            center=ImageCenterSchema(lat=46.5, lon=7.5),
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
        return TestClient("/v1/geo/images")

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
        client = TestClient("/v1/geo/images")
        url = "/nearby?lat=46.5&lon=7.5&radius=100&lang=en&limit=10"
        assert client.get(url).status_code == 200
        assert client.get(url).status_code == 200
        assert stub.calls == 1


@pytest.mark.django_db
class TestCachedOnly:
    """The cached_only fast-call parameter: cache-only answers, never a
    provider call, nothing written back."""

    @pytest.fixture
    def client(self):
        return TestClient("/v1/geo/images")

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
    def place_slug(self, seed_data):
        from server.apps.geometries.models import GeoPlace

        slug = (
            GeoPlace.objects.filter(is_active=True, is_public=True)
            .values_list("slug", flat=True)
            .first()
        )
        assert slug, "seed data provides no public place"
        return slug

    @pytest.fixture
    def fetch(self, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub()
        monkeypatch.setattr(api_images, "fetch_images_for_place", stub)
        return stub

    def test_serves_stale_entry_without_providers(
        self, client, hut_slug, fetch, monkeypatch
    ):
        monkeypatch.setattr(irc, "fresh_seconds", lambda: -1)
        url = f"/hut/{hut_slug}?radius=50&lang=en&limit=20"
        warm = client.get(url)
        assert warm.status_code == 200
        fetch.exc = RuntimeError("provider down")  # any fetch must not happen
        fast = client.get(f"{url}&cached_only=true")
        assert fast.status_code == 200
        assert fast.json() == warm.json()
        assert fetch.calls == 1  # only the warm-up call

    def test_cold_cache_returns_fallback_without_providers(
        self, client, hut_slug, fetch
    ):
        fetch.exc = RuntimeError("provider down")
        response = client.get(
            f"/hut/{hut_slug}?radius=50&lang=en&limit=20&cached_only=true"
        )
        assert response.status_code == 200
        body = response.json()
        # static_map_fallback defaults to true — the map card feature is
        # generated, no provider was contacted.
        assert len(body["features"]) == 1
        assert body["features"][0]["properties"]["is_fallback"] is True
        assert body["metadata"]["total"] == 1
        assert fetch.calls == 0

    def test_cold_cache_opt_out_is_empty(self, client, hut_slug, fetch):
        fetch.exc = RuntimeError("provider down")
        response = client.get(
            f"/hut/{hut_slug}?radius=50&lang=en&limit=20"
            "&cached_only=true&static_map_fallback=false"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["features"] == []
        assert body["metadata"]["total"] == 0
        assert fetch.calls == 0

    def test_cold_cache_does_not_shadow_future_responses(self, client, hut_slug, fetch):
        client.get(f"/hut/{hut_slug}?radius=50&lang=en&limit=20&cached_only=true")
        client.get(f"/hut/{hut_slug}?radius=50&lang=en&limit=20")
        assert fetch.calls == 1  # the empty fast call was not cached

    def test_place_cold_cache_returns_fallback(self, client, place_slug, fetch):
        fetch.exc = RuntimeError("provider down")
        response = client.get(
            f"/place/{place_slug}?radius=50&lang=en&limit=20&cached_only=true"
        )
        assert response.status_code == 200
        features = response.json()["features"]
        assert len(features) == 1
        assert features[0]["properties"]["is_fallback"] is True
        assert fetch.calls == 0

    def test_place_unknown_slug_is_404(self, client, fetch):
        fetch.exc = RuntimeError("provider down")
        response = client.get(
            "/place/does-not-exist-xyz?cached_only=true&radius=50&lang=en&limit=20"
        )
        assert response.status_code == 404
        assert fetch.calls == 0

    def test_hut_unknown_slug_is_404(self, client, fetch):
        fetch.exc = RuntimeError("provider down")
        response = client.get(
            "/hut/does-not-exist-xyz?cached_only=true&radius=50&lang=en&limit=20"
        )
        assert response.status_code == 404
        assert fetch.calls == 0

    def test_nearby_serves_cached_only(self, seed_data, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub(returns_tuple=False)
        monkeypatch.setattr(api_images, "fetch_images_from_providers", stub)
        client = TestClient("/v1/geo/images")
        url = "/nearby?lat=46.5&lon=7.5&radius=100&lang=en&limit=10"
        warm = client.get(url)
        stub.exc = RuntimeError("provider down")
        fast = client.get(f"{url}&cached_only=true")
        assert fast.status_code == 200
        assert fast.json() == warm.json()
        assert stub.calls == 1

    def test_nearby_cold_cache_returns_empty(self, seed_data, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub(returns_tuple=False)
        stub.exc = RuntimeError("provider down")
        monkeypatch.setattr(api_images, "fetch_images_from_providers", stub)
        client = TestClient("/v1/geo/images")
        response = client.get(
            "/nearby?lat=46.5&lon=7.5&radius=100&lang=en&limit=10&cached_only=true"
        )
        assert response.status_code == 200
        assert response.json()["features"] == []
        assert stub.calls == 0

    def test_cached_only_rejects_update_cache(self, client, hut_slug):
        response = client.get(
            f"/hut/{hut_slug}?cached_only=true&update_cache=true&radius=50&lang=en"
        )
        assert response.status_code == 400  # dmr maps validation errors to 400

    def test_cached_hut_images_helper_reads_endpoint_entry(
        self, client, hut_slug, fetch
    ):
        from server.apps.geometries.api_images import cached_hut_images

        client.get(f"/hut/{hut_slug}?radius=50&lang=de&limit=20")  # gallery shape
        cached = cached_hut_images(hut_slug, lang="de")
        assert cached is not None
        # The stub returned no features — the default static_map fallback
        # is the single cached feature, and the og lookup skips it.
        assert len(cached.features) == 1
        props = cached.features[0].properties
        assert props is not None
        assert props.is_fallback is True

    def test_cached_place_images_helper_cold_is_none(self, place_slug):
        from server.apps.geometries.api_images import cached_place_images

        assert cached_place_images(place_slug, lang="en") is None


@pytest.mark.django_db
class TestFailureIsNotCached:
    """The nearby endpoint's exception fallback (stale miss → empty
    collection) must not be written to the response cache: caching it
    poisoned the entry and every later request served the empty
    collection until the freshness window expired."""

    class _FetchStub:
        """Async stand-in for fetch_images_from_providers (nearby shape)."""

        def __init__(self):
            self.calls = 0
            self.exc: Exception | None = None

        async def __call__(self, **kwargs):
            self.calls += 1
            if self.exc is not None:
                raise self.exc
            from tests.apps.geometries.test_image_pinning import _result

            return [_result(provider="wikicommons", source_id="File:CacheGuard.jpg")]

    def test_nearby_exception_response_not_cached(self, seed_data, monkeypatch):
        from server.apps.geometries import api_images

        stub = self._FetchStub()
        stub.exc = RuntimeError("provider down")
        monkeypatch.setattr(api_images, "fetch_images_from_providers", stub)
        client = TestClient("/v1/geo/images")
        url = "/nearby?lat=46.5&lon=7.5&radius=100&lang=en&limit=10"

        first = client.get(url)  # fetch fails, nothing cached to fall back on
        assert first.status_code == 200
        assert first.json()["features"] == []

        stub.exc = None  # providers healthy again
        second = client.get(url)  # must recompute, not serve the poisoned entry
        assert second.status_code == 200
        features = second.json()["features"]
        assert len(features) == 1
        assert features[0]["properties"]["source_id"] == "File:CacheGuard.jpg"
        assert stub.calls == 2

        third = client.get(url)  # the successful aggregation IS cached
        assert third.status_code == 200
        assert third.json() == second.json()
        assert stub.calls == 2
