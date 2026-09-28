"""HTTP-level smoke tests for the organizations API endpoints."""

import pytest

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
        # Pick a listed organization instead of factory-making one:
        # fixture-loaded rows leave pk sequences behind and factory
        # inserts collide with existing ids. Being listed also proves
        # the row passes the endpoint's visibility filters.
        listed = client.get("/v1/organizations/").json()
        assert listed, "No organizations listed - seed data incomplete"
        slug = listed[0]["slug"]
        response = client.get(f"/v1/organizations/{slug}")
        assert response.status_code == 200
        assert response.json()["slug"] == slug
