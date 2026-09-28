"""HTTP-level smoke tests for the availability API endpoints.

The availability endpoints read the cached ``HutAvailability`` table
(no external calls at request time), so rows from the
AvailabilityFactory give deterministic data. Assertions stay flexible
(status + shape), per the external-source nature of the data.
"""

import pytest

from tests.factories.availability import AvailabilityFactory

from django.utils import timezone

from server.apps.huts.models import Hut

pytestmark = pytest.mark.django_db


@pytest.fixture()
def hut_with_availability(seed_data):
    hut = Hut.objects.first()
    assert hut is not None
    today = timezone.localdate()
    AvailabilityFactory(hut=hut, availability_date=today)
    return hut, today


class TestAvailabilityApi:
    def test_availability_geojson(self, hut_with_availability, client):
        _hut, date = hut_with_availability
        response = client.get(f"/v1/huts/availability/{date.isoformat()}.geojson")
        assert response.status_code == 200
        data = response.json()
        assert "features" in data
        assert isinstance(data["features"], list)

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
        assert response.status_code == 200
        assert isinstance(response.json(), (dict, list))
