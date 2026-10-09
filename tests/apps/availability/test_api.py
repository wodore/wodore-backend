"""HTTP-level smoke tests for the availability API endpoints.

The availability endpoints read the cached ``HutAvailability`` table
(no external calls at request time), so rows from the
AvailabilityFactory give deterministic data. Assertions stay flexible
(status + shape), per the external-source nature of the data.

The factory rows reference seed-data organizations: fixture-loaded
rows leave the pk sequences behind, so creating new organizations
from factories collides with existing ids.
"""

import datetime

import pytest

from tests.factories.availability import AvailabilityFactory

from django.utils import timezone

from server.apps.huts.models import Hut
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture()
def hut_with_availability(seed_data):
    hut = Hut.objects.first()
    assert hut is not None
    org = Organization.objects.first()
    assert org is not None
    today = timezone.localdate()
    AvailabilityFactory(hut=hut, source_organization=org, availability_date=today)
    return hut, today


@pytest.fixture()
def hut_with_multiday_availability_unordered(seed_data):
    """Hut with several availability days inserted OUT of date order.

    Consumers read the geojson ``data`` array by index (index 0 must be the
    requested date), so the endpoint must return days sorted by date
    regardless of insertion order.
    """
    hut = Hut.objects.first()
    assert hut is not None
    org = Organization.objects.first()
    assert org is not None
    today = timezone.localdate()
    offsets = [3, 0, 4, 1]  # deliberately unordered insertion
    for offset in offsets:
        AvailabilityFactory(
            hut=hut,
            source_organization=org,
            availability_date=today + datetime.timedelta(days=offset),
            free=offset,
        )
    return hut, today


class TestAvailabilityApi:
    def test_availability_geojson(self, hut_with_availability, client):
        _hut, date = hut_with_availability
        response = client.get(f"/v1/huts/availability/{date.isoformat()}.geojson")
        assert response.status_code == 200
        data = response.json()
        assert "features" in data
        assert isinstance(data["features"], list)

    def test_availability_geojson_days_sorted_by_date(
        self, hut_with_multiday_availability_unordered, client
    ):
        """The geojson ``data`` days must be ordered by date ascending.

        Regression guard: the array is consumed by index (map overlays read
        ``data[0]`` as the requested date), so an unordered response paints
        the wrong day's availability (staging bug 2026-10).
        """
        hut, today = hut_with_multiday_availability_unordered
        response = client.get(
            f"/v1/huts/availability/{today.isoformat()}.geojson?days=8&slugs={hut.slug}"
        )
        assert response.status_code == 200
        data = response.json()
        feature = next(
            f for f in data["features"] if f["properties"]["slug"] == hut.slug
        )
        dates = [day["date"] for day in feature["properties"]["data"]]
        # Non-vacuous: the window must actually contain the shuffled days
        assert len(dates) == 4
        assert dates == sorted(dates)
        # Index 0 is the requested date itself
        assert dates[0] == today.isoformat()

    def test_hut_availability_current(self, hut_with_availability, client):
        hut, date = hut_with_availability
        response = client.get(f"/v1/huts/{hut.slug}/availability/{date.isoformat()}")
        assert response.status_code == 200
        data = response.json()
        # Flexible: shape only - values come from external providers.
        assert isinstance(data, dict)

    def test_hut_availability_trend(self, hut_with_availability, client):
        hut, date = hut_with_availability
        response = client.get(
            f"/v1/huts/{hut.slug}/availability/{date.isoformat()}/trend"
        )
        # Trend data comes from HutAvailabilityHistory; with no history
        # rows the endpoint documents emptiness with 404. Either way the
        # view compiled and executed (a #202-class FieldError is a 500).
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            assert isinstance(response.json(), (dict, list))
