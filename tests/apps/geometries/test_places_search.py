"""HTTP-level smoke test for the geo places search endpoint."""

import pytest

from django.contrib.gis.geos import Point
from django.test import Client

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory

pytestmark = pytest.mark.django_db


class TestPlacesSearchApi:
    def test_search_by_name(self, seed_data: dict[str, int], client: Client):
        # Seeds include geoplaces like "Test Peak Dammastock"; keep the
        # assertion flexible (200 + list) - matching depends on names.
        response = client.get("/v1/geo/places/search", {"q": "Dammastock"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_no_match(self, seed_data: dict[str, int], client: Client):
        response = client.get("/v1/geo/places/search", {"q": "zz-no-such-place-zz"})
        assert response.status_code == 200
        assert response.json() == []

    @staticmethod
    def _make_place(name: str, slug: str) -> GeoPlace:
        """A public accommodation hut under the seeded map tree."""
        accommodation = Category.objects.get(
            slug="accommodation", parent__slug="amenity"
        )
        hut_cat, _ = Category.objects.get_or_create(
            slug="search-hut", parent=accommodation, defaults={"name": "SH"}
        )
        place = GeoPlace.objects.create(
            name=name,
            slug=slug,
            location=Point(7.75, 46.02, srid=4326),
            country_code="CH",
            is_active=True,
            is_public=True,
            domain="amenity",
        )
        GeoPlaceCategory.objects.create(geo_place=place, category=hut_cat)
        return place

    def test_kind_ref_on_fuzzy_path(self, client: Client):
        """Opus review F1: the kind ref must also ship on the >=5-char
        fuzzy path (it was only threaded into the fast path)."""
        self._make_place("Wildhuus", "wildhuus-t1")
        response = client.get(
            "/v1/geo/places/search",
            {"q": "Wildhuus", "fields[places]": "slug,name,kind"},
        )
        assert response.status_code == 200
        results = response.json()
        assert len(results) >= 1
        entry = next(r for r in results if r["slug"] == "wildhuus-t1")
        assert entry["kind"]["identifier"] == "accommodation.search-hut"
        assert entry["kind"]["slug"] == "search-hut"

    def test_wildcards_are_literal(self, client: Client):
        """Opus review F2: % and _ in the query must not act as LIKE
        wildcards — the containment arm escapes metacharacters."""
        self._make_place("Axxberg", "axxberg-t2")
        # underscore: 'A_berg' must NOT match 'Axxberg' (single-char wildcard)
        response = client.get("/v1/geo/places/search", {"q": "A_berg"})
        assert response.status_code == 200
        assert all(r["slug"] != "axxberg-t2" for r in response.json())
        # percent: 'A%berg' must NOT match 'Axxberg' (any-chars wildcard)
        response = client.get("/v1/geo/places/search", {"q": "A%berg"})
        assert response.status_code == 200
        assert all(r["slug"] != "axxberg-t2" for r in response.json())
        # control: the literal name matches
        response = client.get("/v1/geo/places/search", {"q": "Axxberg"})
        assert any(r["slug"] == "axxberg-t2" for r in response.json())
