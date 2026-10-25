"""Tests for the meteo API endpoints."""

import pytest

from django.test import Client

from server.apps.meteo.models import WeatherCode, WeatherCodeSymbolCollection
from server.apps.organizations.models import Organization

pytestmark = [pytest.mark.django_db]

WEATHER_CODES_URL = "/v1/meteo/weather_codes"
WC_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=604800"


@pytest.fixture
def _org(db: None):
    org, _ = Organization.objects.get_or_create(
        slug="test-wmo-org",
        defaults={"name": "Test WMO Org", "is_active": True},
    )
    return org


@pytest.fixture
def collection(_org):
    col, _ = WeatherCodeSymbolCollection.objects.get_or_create(
        slug="weather-icons-outlined-mono",
        defaults={"source_org": _org},
    )
    return col


@pytest.fixture
def alt_collection(_org):
    col, _ = WeatherCodeSymbolCollection.objects.get_or_create(
        slug="alt-test-collection",
        defaults={"source_org": _org},
    )
    return col


@pytest.fixture
def weather_codes(collection: WeatherCodeSymbolCollection):
    codes = []
    for code, desc_day, desc_night in [
        (0, "Clear sky", "Clear sky"),
        (1, "Mainly clear", "Mainly clear"),
        (61, "Rain: slight", "Rain: slight"),
    ]:
        wc, _ = WeatherCode.objects.get_or_create(
            code=code,
            defaults={
                "description_day": desc_day,
                "description_night": desc_night,
            },
        )
        codes.append(wc)
    return codes


class TestWeatherCodesCaching:
    def test_etag_and_cache_control_present(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        response = client.get(WEATHER_CODES_URL)
        assert response.status_code == 200
        assert "ETag" in response
        assert response["Cache-Control"] == WC_CACHE_CONTROL
        etag = response["ETag"]
        assert etag.startswith('"') and etag.endswith('"')

    def test_if_none_match_returns_304_empty_body(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        first = client.get(WEATHER_CODES_URL)
        assert first.status_code == 200
        etag = first["ETag"]

        second = client.get(WEATHER_CODES_URL, HTTP_IF_NONE_MATCH=etag)
        assert second.status_code == 304
        assert second["ETag"] == etag
        assert second["Cache-Control"] == WC_CACHE_CONTROL
        assert second.content == b""

    def test_if_none_match_list_returns_304(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        """Comma-separated If-None-Match list (CDN revalidation form)."""
        etag = client.get(WEATHER_CODES_URL)["ETag"]

        response = client.get(
            WEATHER_CODES_URL,
            HTTP_IF_NONE_MATCH=f'"other-etag", {etag}',
        )
        assert response.status_code == 304

    def test_if_none_match_wildcard_returns_304(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        """If-None-Match: * must match any current representation."""
        response = client.get(WEATHER_CODES_URL, HTTP_IF_NONE_MATCH="*")
        assert response.status_code == 304

    def test_etag_varies_by_lang(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        en = client.get(WEATHER_CODES_URL, {"lang": "en"})["ETag"]
        de = client.get(WEATHER_CODES_URL, {"lang": "de"})["ETag"]
        assert en != de

    def test_etag_varies_by_collection(
        self,
        weather_codes: list[WeatherCode],
        alt_collection: WeatherCodeSymbolCollection,
        client: Client,
    ):
        """Different collection slug must produce a different ETag."""
        default = client.get(WEATHER_CODES_URL)["ETag"]
        other = client.get(WEATHER_CODES_URL, {"collection": alt_collection.slug})
        assert other.status_code == 200
        assert other["ETag"] != default

    def test_stale_etag_returns_200(
        self, weather_codes: list[WeatherCode], client: Client
    ):
        first = client.get(WEATHER_CODES_URL)
        assert first.status_code == 200

        stale = client.get(WEATHER_CODES_URL, HTTP_IF_NONE_MATCH='"stale-etag-value"')
        assert stale.status_code == 200
        assert "ETag" in stale
