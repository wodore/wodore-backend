"""API + admin tests for place parties (OpenSpec geoplace-parties 4.1/4.2).

The role vocabulary is seeded by migrations on the test database, so
these tests build associations against the seeded ``role.*``
categories.
"""

from unittest.mock import MagicMock

import pytest

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.parties import PartyFactory

from django.contrib.admin import AdminSite

from server.apps.categories.models import Category
from server.apps.external_links.models import ExternalLink
from server.apps.geometries.admin._geoplace import GeoPlaceAdmin
from server.apps.geometries.models import GeoPlace, GeoPlaceParty
from server.apps.parties.models import PartyLink

pytestmark = pytest.mark.django_db


def _link_party(
    place: GeoPlace,
    slug: str = "volg",
    role_slug: str = "operator",
    url: str | None = None,
) -> None:
    party = PartyFactory(slug=slug, name=slug.title())
    GeoPlaceParty.objects.create(
        geo_place=place,
        party=party,
        role=Category.objects.get(slug=role_slug, parent__slug="role"),
    )
    if url:
        link = ExternalLink(url=url, label=slug.title())
        link.save(skip_health_check=True)
        PartyLink.objects.create(party=party, external_link=link)


class TestSearchPartiesField:
    def test_parties_included_when_selected(self, client):
        place = GeoPlaceFactory(name="Volg Zermatt")
        _link_party(place, slug="volg", url="https://volg.example.com")

        response = client.get(
            "/v1/geo/places/search",
            {"q": "Volg Zermatt", "fields[places]": "id,name,parties"},
        )

        assert response.status_code == 200
        parties = response.json()[0]["parties"]
        assert parties[0]["role"] == "role.operator"
        assert parties[0]["slug"] == "volg"
        assert parties[0]["name"] == "Volg"
        assert parties[0]["links"][0]["url"] == "https://volg.example.com"

    def test_parties_absent_when_not_selected(self, client):
        place = GeoPlaceFactory(name="Volg Zermatt")
        _link_party(place, slug="volg")

        response = client.get(
            "/v1/geo/places/search",
            {"q": "Volg Zermatt", "fields[places]": "id,name"},
        )

        assert response.status_code == 200
        assert "parties" not in response.json()[0]

    def test_nested_fields_narrowing_on_nearby(self, client):
        place = GeoPlaceFactory(name="Volg Zermatt")
        _link_party(place, slug="volg", url="https://volg.example.com")

        response = client.get(
            "/v1/geo/places/nearby",
            {
                "lat": place.location.y,
                "lon": place.location.x,
                "radius": 1000,
                "fields[places]": "id,parties",
                "fields[parties]": "slug",
            },
        )

        assert response.status_code == 200, f"nearby failed: {response.content}"


class TestAmenityPartiesField:
    def test_amenity_detail_includes_parties(self, client):
        from server.apps.geometries.models import AmenityDetail

        place = GeoPlaceFactory(name="Volg Zermatt", detail_type="amenity")
        AmenityDetail.objects.create(geo_place=place)
        _link_party(place, slug="volg", url="https://volg.example.com")

        response = client.get(f"/v1/geo/places/amenity/{place.pk}")

        assert response.status_code == 200
        parties = response.json()["parties"]
        assert parties[0]["role"] == "role.operator"
        assert parties[0]["slug"] == "volg"
        assert parties[0]["links"][0]["url"] == "https://volg.example.com"


class TestPartyInlineTracking:
    def test_party_formset_save_marks_place_protected(self):
        place = GeoPlaceFactory(is_modified=False)
        assert "parties" not in (place.protected_fields or [])

        form = MagicMock()
        form.instance = place
        formset = MagicMock()
        formset.model = GeoPlaceParty
        formset.has_changed.return_value = True

        admin_instance = GeoPlaceAdmin(GeoPlace, AdminSite())
        admin_instance.save_formset(
            request=MagicMock(), form=form, formset=formset, change=True
        )

        place.refresh_from_db()
        assert place.is_modified
        assert "parties" in place.protected_fields

    def test_unchanged_formset_leaves_place_alone(self):
        place = GeoPlaceFactory(is_modified=False)

        form = MagicMock()
        form.instance = place
        formset = MagicMock()
        formset.model = GeoPlaceParty
        formset.has_changed.return_value = False

        admin_instance = GeoPlaceAdmin(GeoPlace, AdminSite())
        admin_instance.save_formset(
            request=MagicMock(), form=form, formset=formset, change=True
        )

        place.refresh_from_db()
        assert not place.is_modified
        assert "parties" not in (place.protected_fields or [])
