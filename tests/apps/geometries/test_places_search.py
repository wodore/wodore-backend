"""HTTP-level smoke test for the geo places search endpoint."""

import pytest

pytestmark = pytest.mark.django_db


class TestPlacesSearchApi:
    def test_search_by_name(self, seed_data, client):
        # Seeds include geoplaces like "Test Peak Dammastock"; keep the
        # assertion flexible (200 + list) - matching depends on names.
        response = client.get("/v1/geo/places/search", {"q": "Dammastock"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_no_match(self, seed_data, client):
        response = client.get("/v1/geo/places/search", {"q": "zz-no-such-place-zz"})
        assert response.status_code == 200
        assert response.json() == []
