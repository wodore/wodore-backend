"""Provider httpx clients must use the configured per-provider timeout.

P0 2026-10-05: every provider constructed ``httpx.AsyncClient(timeout=30.0)``
and the Wikimedia provider runs several sequential strategy calls per
request — one cold fan-out could hold a request for 30-60s+ until an
upstream client cancelled it. The timeout now comes from
``IMAGES_PROVIDER_HTTP_TIMEOUT_SECONDS`` (default 10s); these tests pin
every ``AsyncClient`` construction site to it.

Approach: ``httpx.AsyncClient`` is replaced by a stub that records its
``timeout=`` argument and raises immediately, so no request is made —
each provider's own error handling then unwinds the fetch. Only the
constructor argument is under test. (Mapillary is still an unimplemented
stub without HTTP calls — nothing to pin there.)
"""

import asyncio
import contextlib

import httpx
import pytest

from django.test import override_settings

from server.apps.geometries.providers.base import (
    _get_image_dimensions_from_headers,
    provider_http_timeout,
)
from server.apps.geometries.providers.camptocamp import CamptocampProvider
from server.apps.geometries.providers.panoramax import PanoramaxProvider
from server.apps.geometries.providers.refugesinfo import RefugesInfoProvider
from server.apps.geometries.providers.schemas import GeoPlaceSchema, Source
from server.apps.geometries.providers.wikimedia_commons import (
    WikimediaCommonsProvider,
)

pytestmark = [pytest.mark.django_db]


class _Stop(Exception):
    """Raised by the stub client right after its construction is captured."""


@pytest.fixture
def captured_timeouts(monkeypatch):
    """Record the ``timeout=`` of every AsyncClient a provider constructs."""
    captured = []

    class _CapturingClient:
        def __init__(self, *args, **kwargs):
            captured.append(kwargs.get("timeout"))
            raise _Stop()

    monkeypatch.setattr(httpx, "AsyncClient", _CapturingClient)
    return captured


class TestTimeoutSetting:
    def test_default_is_ten_seconds(self):
        assert provider_http_timeout() == 10.0

    @override_settings(IMAGES_PROVIDER_HTTP_TIMEOUT_SECONDS=12.5)
    def test_reads_the_setting(self):
        assert provider_http_timeout() == 12.5


class TestWikimediaStrategyClients:
    """Wikimedia constructs one client per strategy call (four sites)."""

    @pytest.mark.parametrize(
        "method",
        [
            "_fetch_wikidata_spatial",
            "_fetch_wikidata_by_qids",
            "_fetch_commons_geosearch",
            "_fetch_commons_category_images",
        ],
    )
    def test_strategy_client_uses_configured_timeout(self, captured_timeouts, method):
        provider = WikimediaCommonsProvider()
        call = getattr(provider, method)
        with contextlib.suppress(Exception):
            if method == "_fetch_wikidata_by_qids":
                coro = call({"Q123"}, 46.5, 7.5, 10, httpx)
            elif method == "_fetch_commons_category_images":
                coro = call("Category:Test", 46.5, 7.5, 10, httpx)
            else:
                coro = call(46.5, 7.5, 50.0, 10, set(), httpx)
            asyncio.run(coro)
        assert captured_timeouts == [provider_http_timeout()]


class TestOtherProviderClients:
    """Camptocamp, Panoramax and RefugesInfo each construct one client."""

    def test_camptocamp_client_uses_configured_timeout(self, captured_timeouts):
        with contextlib.suppress(Exception):
            asyncio.run(
                CamptocampProvider().fetch([], 46.5, 7.5, 50.0, 10, update_cache=True)
            )
        assert captured_timeouts == [provider_http_timeout()]

    def test_panoramax_client_uses_configured_timeout(self, captured_timeouts):
        with contextlib.suppress(Exception):
            asyncio.run(
                PanoramaxProvider().fetch([], 46.5, 7.5, 50.0, 10, update_cache=True)
            )
        assert captured_timeouts == [provider_http_timeout()]

    def test_refugesinfo_client_uses_configured_timeout(self, captured_timeouts):
        place = GeoPlaceSchema(
            slug="test-place",
            name="Test Place",
            lat=46.5,
            lon=7.5,
            sources=[Source(slug="refuges", source_id="123")],
        )
        with contextlib.suppress(Exception):
            asyncio.run(
                RefugesInfoProvider().fetch(
                    [place], 46.5, 7.5, 50.0, 10, update_cache=True
                )
            )
        assert captured_timeouts == [provider_http_timeout()]

    @override_settings(IMAGES_PROVIDER_HTTP_TIMEOUT_SECONDS=12.5)
    def test_configured_value_flows_to_clients(self, captured_timeouts):
        with contextlib.suppress(Exception):
            asyncio.run(
                CamptocampProvider().fetch([], 46.5, 7.5, 50.0, 10, update_cache=True)
            )
        assert captured_timeouts == [12.5]


class TestDimensionProbeClient:
    """The dimension probe in base.py shares the provider timeout."""

    def test_dimension_probe_uses_configured_timeout(self, captured_timeouts):
        result = asyncio.run(_get_image_dimensions_from_headers("http://x/t.jpg"))
        assert result is None  # the stub aborts the probe
        assert captured_timeouts == [provider_http_timeout()]
