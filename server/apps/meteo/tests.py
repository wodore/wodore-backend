"""Tests for the meteo endpoints.

Focus: the weather-code SVG redirect (regression — the 302 response was
not declared in ``@modify``, so dmr's response validation rejected it
with a ``validation_error`` body instead of redirecting).
"""

from __future__ import annotations

import pytest

from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client

from server.apps.licenses.models import License
from server.apps.meteo.models import (
    WeatherCode,
    WeatherCodeSymbol,
    WeatherCodeSymbolCollection,
)
from server.apps.organizations.models import Organization
from server.apps.symbols.models import Symbol

SVG_BODY = b'<svg xmlns="http://www.w3.org/2000/svg"/>'


def _reset_pk_sequence(model) -> None:
    """Sync a table's ``id`` sequence with ``MAX(id)``.

    Test databases cloned from the dev/template data contain rows
    inserted with explicit ids, leaving the sequence behind; creating
    new rows would collide with existing pks otherwise.
    """
    table = model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))",
            [table],
        )


@pytest.mark.django_db
class TestWeatherCodeSvg:
    """GET /v1/meteo/symbol/{collection}/{time}/{code}.svg"""

    @pytest.fixture
    def weather_svg(self):
        """Collection with a day symbol for WMO code 0."""
        license = License.objects.create(slug="license-test-clear")
        symbol = Symbol(
            slug="test-clear-day", style=Symbol.StyleChoices.color, license=license
        )
        symbol.svg_file.save("clear-day.svg", ContentFile(SVG_BODY), save=True)

        _reset_pk_sequence(Organization)
        org = Organization.objects.create(slug="test-org-xy", name="Test Org")
        collection = WeatherCodeSymbolCollection.objects.create(
            slug="test-collection-xy", source_org=org
        )
        code = WeatherCode.objects.create(
            code=9001,
            slug="test-clear",
            description_day="Clear sky",
            description_night="Clear sky",
        )
        WeatherCodeSymbol.objects.create(
            weather_code=code,
            collection=collection,
            symbol_day=symbol,
        )
        return symbol

    def test_redirects_to_svg(self, weather_svg):
        response = Client().get("/v1/meteo/symbol/test-collection-xy/day/9001.svg")

        assert response.status_code == 302
        assert response["Location"] == weather_svg.svg_file.url
        assert response["Cache-Control"] == "public, max-age=604800"

    def test_unknown_collection_returns_404(self):
        response = Client().get("/v1/meteo/symbol/test-nope/day/0.svg")

        assert response.status_code == 404

    def test_unknown_code_returns_404(self, weather_svg):
        response = Client().get("/v1/meteo/symbol/test-collection-xy/day/99.svg")

        assert response.status_code == 404

    def test_code_without_day_symbol_returns_404(self, weather_svg):
        WeatherCode.objects.create(
            code=9002,
            slug="test-mainly-clear",
            description_day="Mainly clear",
            description_night="Mainly clear",
        )

        response = Client().get("/v1/meteo/symbol/test-collection-xy/day/1.svg")

        assert response.status_code == 404
