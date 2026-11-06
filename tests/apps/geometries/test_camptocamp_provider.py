"""Tests for the camptocamp provider waypoint-type filter.

The /waypoints bbox search cannot filter types server-side (``t=`` etc. are
silently ignored), so the provider skips every waypoint whose
``waypoint_type`` is not an overnight place (hut, gite, shelter, camp_site,
bivouac) — hut galleries should show the place, not nearby summits, passes
and parking lots. Routes are never queried (they live under /routes).
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from django.test import Client

from server.apps.geometries.providers.camptocamp import CamptocampProvider


def _waypoint(document_id: int, waypoint_type: str) -> dict[str, Any]:
    return {"document_id": document_id, "waypoint_type": waypoint_type}


@pytest.fixture
def provider() -> CamptocampProvider:
    return CamptocampProvider()


def _run_fetch(
    provider: CamptocampProvider, waypoints: list[dict[str, Any]]
) -> list[int]:
    """Run fetch() with the HTTP boundary stubbed out; returns the waypoint
    ids whose images were fetched."""

    async def _waypoints(client: Client, bbox: str):
        return waypoints

    async def _no_cache(*args: Any, **kwargs: Any):
        return None

    async def _store(*args: Any, **kwargs: Any):
        return None

    fetch_images = AsyncMock(return_value=[])
    provider._fetch_waypoints = _waypoints  # type: ignore[method-assign]
    provider._fetch_waypoint_images = fetch_images  # type: ignore[method-assign]
    provider._get_cached_results = _no_cache  # type: ignore[method-assign]
    provider._set_cached_results = _store  # type: ignore[method-assign]
    asyncio.run(provider.fetch([], 46.0, 7.5, 50, update_cache=True))
    return [call.args[1] for call in fetch_images.await_args_list]


class TestWaypointTypeFilter:
    def test_only_overnight_places_donate_images(self, provider: CamptocampProvider):
        waypoints = [
            _waypoint(1, "hut"),
            _waypoint(2, "pass"),
            _waypoint(3, "summit"),
            _waypoint(4, "gite"),
            _waypoint(5, "shelter"),
            _waypoint(6, "camp_site"),
            _waypoint(7, "bivouac"),
            _waypoint(8, "climbing_outdoor"),
            _waypoint(9, "parking"),
            _waypoint(10, "access"),
            _waypoint(11, "webcam"),
            _waypoint(12, "locality"),
        ]
        assert _run_fetch(provider, waypoints) == [1, 4, 5, 6, 7]

    def test_unknown_type_is_skipped(self, provider: CamptocampProvider):
        assert _run_fetch(provider, [_waypoint(1, "virtual"), _waypoint(2, "hut")]) == [
            2
        ]

    def test_missing_type_is_skipped(self, provider: CamptocampProvider):
        assert _run_fetch(provider, [{"document_id": 1}]) == []

    def test_donor_types_are_the_agreed_set(self, provider: CamptocampProvider):
        assert provider.image_waypoint_types == frozenset(
            {"hut", "gite", "shelter", "camp_site", "bivouac"}
        )
