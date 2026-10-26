"""Tests for GeoPlace and related models, validators."""

import pytest

from tests.factories.geometries import GeoPlaceFactory

from django.contrib.gis.geos import Point

from server.apps.geometries.models import GeoPlace

pytestmark = pytest.mark.django_db


class TestSlugCollisionRetry:
    """A unique collision on a freshly minted geoplace slug re-mints a
    new suffix and retries inside a savepoint (review comment 2)."""

    def test_collision_remints_and_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        GeoPlaceFactory(slug="aaaaa-11111")

        minted = iter(["aaaaa-11111", "bbbbb-22222"])

        def fake_mint(*_args: object, **_kwargs: object) -> str:
            return next(minted)

        monkeypatch.setattr(GeoPlace, "generate_unique_slug", fake_mint)

        place = GeoPlace(
            name="Retry Place",
            location=Point(7.7343, 46.0234),
            country_code="CH",
        )
        place.save()

        assert place.slug == "bbbbb-22222"
