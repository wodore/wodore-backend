"""HTTP-level smoke tests for the organizations API endpoints."""

import pytest

from tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


class TestOrganizationsApi:
    def test_organizations_list(self, seed_data, client):
        response = client.get("/v1/organizations/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for org in data:
            assert org["slug"]

    def test_organization_detail(self, seed_data, client):
        # Use a factory-made organization so the detail lookup is
        # deterministic regardless of seed visibility filters.
        org = OrganizationFactory()
        response = client.get(f"/v1/organizations/{org.slug}")
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == org.slug
