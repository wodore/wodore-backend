"""GeoPlace admin changelist filters (sources + category parent).

Pins the PO-requested filters: filtering places by source
organization and by category parent (e.g. all accommodations).
"""

import pytest

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser(db: None):  # type: ignore[no-untyped-def]
    return get_user_model().objects.create_superuser(  # type: ignore  # custom manager method inference gap
        email="filter-admin@example.com", password="pw"
    )


@pytest.fixture
def admin_client(superuser) -> Client:  # type: ignore[no-untyped-def]
    client = Client()
    client.force_login(superuser)
    return client


class TestGeoPlaceChangelistFilters:
    def test_changelist_renders_source_and_parent_filters(self, admin_client: Client):
        url = reverse("admin:geometries_geoplace_changelist")
        response = admin_client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        # both filter widgets are registered and rendered in the sidebar
        assert "categories__parent" in content
        assert "source_set" in content

    def test_category_parent_filter_selects_only_matching_places(
        self, admin_client: Client
    ):
        from tests.factories.geometries import GeoPlaceFactory

        from server.apps.categories.models import Category

        parent = Category.objects.create(slug="filter-parent")
        child = Category.objects.create(slug="filter-child", parent=parent)
        categorized = GeoPlaceFactory(category_list=[child])
        unrelated = GeoPlaceFactory()

        url = reverse("admin:geometries_geoplace_changelist")
        response = admin_client.get(url, {"categories__parent__id": parent.pk})

        assert response.status_code == 200
        content = response.content.decode()
        assert categorized.slug in content
        assert unrelated.slug not in content


class TestGeoPlaceTilemap:
    """The tile map debug view (restored clustered tile contract).

    0076 restored the clustered ``get_geoplaces_for_tiles`` — the view's
    template filters on ``count``/``parent_slug`` (both back in the
    tiles) and requests the current field set.
    """

    def test_tilemap_renders_with_restored_contract(self, admin_client: Client) -> None:
        url = reverse("admin:geometries_geoplace_tilemap")
        response = admin_client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        # the tile URL field set matches the restored function contract
        # (flat category props + the opt-in categories/sources arrays —
        # no `category` object token, that projection is gone)
        assert (
            "params.fields = 'color,parent_color,parent_slug,"
            "categories,sources,importance,count,name,slug'" in content
        )
        # layer filters read the restored count/parent_slug properties
        assert "['get', 'count']" in content
        assert "['get', 'parent_slug']" in content
