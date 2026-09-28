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

    def test_organization_factory_after_seeded_fixtures(self, seed_data):
        # Regression: fixture-loaded organizations carry explicit pks and
        # left the pk sequence behind, so factory inserts collided with
        # existing ids (duplicate key violations). conftest resets the
        # sequences after seeding - this locks that in.
        org = OrganizationFactory()
        assert org.pk
