"""Tests for the Panoramax provider producer allow-list.

The provider queries the official Panoramax instance and skips every
image whose ``geovisio:producer`` is not on ``approved_producers`` (see
module docstring of ``panoramax.py`` for the rationale). The server-side
producer filters are ignored by the API, so the provider over-fetches
beyond the requested limit to keep approved images reachable behind
robot-import floods. These tests pin that behavior offline.
"""

import pytest

from server.apps.geometries.providers.panoramax import PanoramaxProvider


def _stac_feature(producer: str | None) -> dict:
    """Minimal STAC item as returned by /api/search (official instance)."""
    properties: dict = {
        "datetime": "2024-07-29T13:53:32+00:00",
        "license": "CC-BY-SA-4.0",
    }
    if producer is not None:
        properties["geovisio:producer"] = producer
    return {
        "id": "9eeff5d9-d74f-4076-973e-d2afd9388743",
        "collection": "a7cf963f-8d1c-4bac-9717-e3149f5f9fff",
        "geometry": {"type": "Point", "coordinates": [7.5001, 46.5001]},
        "properties": properties,
        "assets": {
            "hd": {
                "href": "https://api.panoramax.xyz/api/pictures/x/hd.jpg",
                "width": 4000,
                "height": 3000,
            },
            "sd": {
                "href": "https://api.panoramax.xyz/api/pictures/x/sd.jpg",
                "width": 1920,
                "height": 1080,
            },
        },
    }


class TestDefaultApiBase:
    def test_defaults_to_official_instance(self):
        """Official instance carries the federated MapComplete uploads."""
        assert PanoramaxProvider().api_base == "https://api.panoramax.xyz"


class TestFetchLimit:
    """Server-side producer filters are ignored, so we over-fetch."""

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            (10, 200),  # raised to the minimum: see behind robot floods
            (100, 200),
            (300, 300),  # in-range limits pass through
            (500, 500),
            (1000, 500),  # capped at the API maximum
        ],
    )
    def test_fetch_limit_is_clamped(self, requested, expected):
        assert PanoramaxProvider().fetch_limit_for(requested) == expected


class TestProducerAllowList:
    @pytest.mark.parametrize(
        "producer",
        [
            "mapcomplete",
            "MapComplete",  # compared case-insensitively
        ],
    )
    def test_approved_producer_is_parsed(self, producer):
        result = PanoramaxProvider()._parse_stac_item(
            _stac_feature(producer), 46.5, 7.5
        )
        assert result is not None
        assert result.provider == "panoramax"
        assert result.author == producer
        # Canonical viewer deep link (hash params) against the configured base
        assert result.source_url == (
            "https://api.panoramax.xyz/"
            "#pic=9eeff5d9-d74f-4076-973e-d2afd9388743"
            "&seq=a7cf963f-8d1c-4bac-9717-e3149f5f9fff"
        )

    @pytest.mark.parametrize(
        "producer",
        [
            "p4n-pics",  # bulk "Batch …" street imports
            "Robot8A",
            "ordinatous",
            "some-random-user",
            "",
        ],
    )
    def test_non_approved_producer_is_skipped_entirely(self, producer):
        result = PanoramaxProvider()._parse_stac_item(
            _stac_feature(producer), 46.5, 7.5
        )
        assert result is None

    def test_missing_producer_is_skipped(self):
        result = PanoramaxProvider()._parse_stac_item(_stac_feature(None), 46.5, 7.5)
        assert result is None
