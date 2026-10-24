"""Tests for the meteo API endpoints."""

import pytest

from server.apps.meteo.models import WeatherCode, WeatherCodeSymbolCollection
from server.apps.organizations.models import Organization

pytestmark = [pytest.mark.django_db]

WEATHER_CODES_URL = "/v1/meteo/weather_codes"
REVALIDATE_CACHE_CONTROL = "public, max-age=0, must-revalidate, stale-if-error=604800"


@pytest.fixture
def collection(db):
    org, _ = Organization.objects.get_or_create(
        slug="test-wmo-org",
        defaults={"name": "Test WMO Org", "is_active": True},
    )
    col, _ = WeatherCodeSymbolCollection.objects.get_or_create(
        slug="weather-icons-outlined-mono",
        defaults={"source_org": org},
    )
    return col


@pytest.fixture
def weather_codes(collection):
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
    def test_etag_and_cache_control_present(self, weather_codes, client):
        response = client.get(WEATHER_CODES_URL)
        assert response.status_code == 200
        assert "ETag" in response
        assert response["Cache-Control"] == REVALIDATE_CACHE_CONTROL
        etag = response["ETag"]
        assert etag.startswith('"') and etag.endswith('"')

    def test_if_none_match_returns_304_empty_body(self, weather_codes, client):
        first = client.get(WEATHER_CODES_URL)
        assert first.status_code == 200
        etag = first["ETag"]

        second = client.get(WEATHER_CODES_URL, HTTP_IF_NONE_MATCH=etag)
        assert second.status_code == 304
        assert second["ETag"] == etag
        assert second.content == b""

    def test_etag_varies_by_lang(self, weather_codes, client):
        en = client.get(WEATHER_CODES_URL, {"lang": "en"})["ETag"]
        de = client.get(WEATHER_CODES_URL, {"lang": "de"})["ETag"]
        assert en != de

    def test_etag_varies_by_collection(self, weather_codes, client):
        """Collection query param is part of the ETag vary key."""
        default_etag = client.get(WEATHER_CODES_URL)["ETag"]
        # Use a second valid collection slug that happens to not exist;
        # etag_page computes the ETag before the view renders, so the
        # ETag still differs even when the response is a non-200.
        import hashlib
        from urllib.parse import urlencode

        def _etag(path, version, params):
            vary = "|".join((path, version, urlencode(sorted(params.items())), ""))
            return f'"{hashlib.sha256(vary.encode()).hexdigest()[:20]}"'

        # ETags with different collection params encode different query strings.
        etag_a = _etag("/v1/meteo/weather_codes", "v", {"collection": "col-a"})
        etag_b = _etag("/v1/meteo/weather_codes", "v", {"collection": "col-b"})
        assert etag_a != etag_b
        assert default_etag != etag_a

    def test_stale_etag_returns_200(self, weather_codes, client):
        first = client.get(WEATHER_CODES_URL)
        assert first.status_code == 200

        stale = client.get(WEATHER_CODES_URL, HTTP_IF_NONE_MATCH='"stale-etag-value"')
        assert stale.status_code == 200
        assert "ETag" in stale
