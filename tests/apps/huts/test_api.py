"""HTTP-level smoke tests for the huts API endpoints.

These guard the public read surface (list, detail, geojson, bookings,
hut types) against model/API drift: e.g. #190 replaced
HutImageAssociation.order with score but missed the JSONBAgg ordering
in get_huts/get_hut, 500-ing every hut request on staging (#202) -
any single request here would have caught it at queryset compilation
time, before deploy.

Uses the session-scoped seed_data fixture (real huts with
organizations and image associations).
"""

import pytest

from server.apps.huts.models import Hut


@pytest.mark.django_db
class TestHutsApi:
    def test_huts_list(self, seed_data, client):
        response = client.get("/v1/huts/huts", {"limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 2
        for hut in data:
            assert hut["slug"]
            assert hut["name"]

    def test_hut_detail(self, seed_data, client):
        hut = Hut.objects.first()
        assert hut is not None
        response = client.get(f"/v1/huts/{hut.slug}")
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == hut.slug
        assert data["name"] == hut.name
        # The annotate-heavy relations that broke in #202/#190:
        assert "sources" in data
        assert "images" in data

    def test_hut_detail_unknown_slug(self, seed_data, client):
        response = client.get("/v1/huts/does-not-exist-xyz")
        assert response.status_code == 404

    def test_huts_geojson(self, seed_data, client):
        response = client.get("/v1/huts/huts.geojson")
        assert response.status_code == 200
        data = response.json()
        assert "features" in data
        assert isinstance(data["features"], list)

    def test_hut_types_list(self, seed_data, client):
        response = client.get("/v1/huts/types/list")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_hut_types_records(self, seed_data, client):
        response = client.get("/v1/huts/types/records")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


@pytest.mark.django_db
class TestHutBookingsApi:
    """Deprecated but still live endpoints (used until the frontend fully
    migrates to availability.geojson)."""

    def test_hut_bookings(self, seed_data, client):
        response = client.get("/v1/huts/bookings")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_hut_bookings_geojson(self, seed_data, client):
        response = client.get("/v1/huts/bookings.geojson")
        assert response.status_code == 200
        assert "features" in response.json()
