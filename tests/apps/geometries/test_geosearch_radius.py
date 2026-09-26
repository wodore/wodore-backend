"""Commons geosearch must send ggsradius in METERS (MediaWiki bounds 10–10000).

The old code converted the endpoint's meter radius to kilometers — out of
range for every query, so the generator errored and geosearch silently
returned nothing (nearby Wikimedia images were limited to P18/category
results; the geosearch fallback never contributed).
"""

import asyncio
from typing import Any, Self

from server.apps.geometries.providers.wikimedia_commons import (
    WikimediaCommonsProvider,
)


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """Records every GET's params; answers with an empty page set."""

    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def get(self, url: str, params: dict[str, Any]) -> _Response:
        _FakeAsyncClient.calls.append(params)
        return _Response({"query": {"pages": {}}})


class _FakeHttpx:
    AsyncClient = _FakeAsyncClient


def _ggsradius_values(radius_m: float) -> list[Any]:
    """Run one geosearch fetch; return the ggsradius of every API call."""
    _FakeAsyncClient.calls = []
    provider = WikimediaCommonsProvider()
    asyncio.run(
        provider._fetch_commons_geosearch(
            lat=46.0,
            lon=7.75,
            radius=radius_m,
            limit=10,
            place_qids=set(),
            httpx=_FakeHttpx,
        )
    )
    assert _FakeAsyncClient.calls, "provider made no API calls"
    return [c["ggsradius"] for c in _FakeAsyncClient.calls]


class TestGeosearchRadiusUnit:
    def test_meters_passed_through(self):
        # 5000 m must stay 5000 — the old code sent 5 (km), which the API
        # rejects as out of range (10–10000), silently emptying geosearch.
        values = _ggsradius_values(5000)
        assert set(values) == {5000}
        assert len(values) == 3  # metadata pass + two thumb-bucket passes

    def test_clamped_to_api_maximum(self):
        assert set(_ggsradius_values(15000)) == {10000}

    def test_clamped_to_api_minimum(self):
        assert set(_ggsradius_values(5)) == {10}

    def test_all_passes_share_the_radius(self):
        values = _ggsradius_values(3000)
        assert len(set(values)) == 1
