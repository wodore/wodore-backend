"""HTTP-level smoke tests for the huts API endpoints.

These guard the public read surface (list, detail, geojson, bookings,
categories) against model/API drift: e.g. #190 replaced
HutImageAssociation.order with score but missed the JSONBAgg ordering
in get_huts/get_hut, 500-ing every hut request on staging (#202) -
any single request here would have caught it at queryset compilation
time, before deploy.

Uses the session-scoped seed_data fixture (real huts with
organizations and image associations).
"""

import pytest

from server.apps.categories.models import Category
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
        # The embedded hut type must carry its (localized) name — a plain
        # ``name_i18n`` validation alias dropped the ``name`` key of the
        # _resolve_symbol dict and served null, hiding bed counts in the
        # apps (unreleased API regression, caught on staging).
        assert data["type_open"]["slug"] == hut.hut_type_open.slug  # pyright: ignore[reportOptionalSubscript]
        assert data["type_open"]["name"], data["type_open"]  # pyright: ignore[reportOptionalSubscript]
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


@pytest.mark.django_db
class TestHutBookingsApi:
    """Deprecated but still live endpoints (until the frontend fully
    migrates to availability.geojson).

    The booking data comes from external provider APIs which are not
    reachable from the test environment: with no data the endpoint
    returns its documented 503. Both 200 and 503 prove the endpoint
    compiled and executed its query path - a FieldError-class bug
    (see #202) would surface as 500 instead.
    """

    def test_hut_bookings(self, seed_data, client):
        response = client.get("/v1/huts/bookings")
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert isinstance(response.json(), list)

    def test_hut_bookings_geojson(self, seed_data, client):
        response = client.get("/v1/huts/bookings.geojson")
        assert response.status_code in (200, 503)
        if response.status_code == 200:
            assert "features" in response.json()


@pytest.mark.django_db
class TestCategoriesApi:
    """Categories replaced the removed hut-types endpoints as the
    type taxonomy source (see server/apps/huts/api/__init__.py)."""

    @pytest.fixture()
    def root_category(self, seed_data):
        root = Category.objects.filter(parent__isnull=True).first()
        assert root is not None, "No root category - seed data incomplete"
        return root

    def test_category_tree(self, root_category, client):
        response = client.get(f"/v1/categories/tree/{root_category.slug}")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_category_list(self, root_category, client):
        response = client.get(f"/v1/categories/list/{root_category.slug}")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
