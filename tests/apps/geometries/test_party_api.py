"""API + admin tests for place parties (OpenSpec geoplace-parties 4.1/4.2).

The role vocabulary is seeded by migrations on the test database, so
these tests build associations against the seeded ``role.*``
categories.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.parties import PartyFactory

from django.contrib.admin import AdminSite
from django.test import Client

from server.apps.categories.models import Category
from server.apps.external_links.models import ExternalLink
from server.apps.geometries.admin._geoplace import GeoPlaceAdmin
from server.apps.geometries.models import (
    GeoPlace,
    GeoPlaceCategory,
    GeoPlaceExternalLink,
    GeoPlaceParty,
)
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
    def test_parties_included_when_selected(self, client: Client) -> None:
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

    def test_parties_absent_when_not_selected(self, client: Client) -> None:
        place = GeoPlaceFactory(name="Volg Zermatt")
        _link_party(place, slug="volg")

        response = client.get(
            "/v1/geo/places/search",
            {"q": "Volg Zermatt", "fields[places]": "id,name"},
        )

        assert response.status_code == 200
        assert "parties" not in response.json()[0]

    def test_nested_fields_narrowing_on_nearby(self, client: Client) -> None:
        place = GeoPlaceFactory(name="Volg Zermatt")
        _link_party(place, slug="volg", url="https://volg.example.com")

        response = client.get(
            "/v1/geo/places/nearby",
            {
                "lat": str(place.location.y),
                "lon": str(place.location.x),
                "radius": "1000",
                "fields[places]": "slug,parties",
                "fields[parties]": "slug",
            },
        )

        assert response.status_code == 200, f"nearby failed: {response.content}"


class TestPlaceDetailPartiesField:
    def test_place_detail_includes_parties(self, client: Client) -> None:
        from server.apps.geometries.models import AmenityDetail

        place = GeoPlaceFactory(name="Volg Zermatt", kind_slug="map.amenity")
        AmenityDetail.objects.create(geo_place=place)
        _link_party(place, slug="volg", url="https://volg.example.com")

        response = client.get(f"/v1/geo/places/{place.slug}")

        assert response.status_code == 200
        parties = response.json()["parties"]
        assert parties[0]["role"] == "role.operator"
        assert parties[0]["slug"] == "volg"
        assert parties[0]["links"][0]["url"] == "https://volg.example.com"


class TestPartyInlineTracking:
    """Manual association edits mark the place modified + record
    protection: parties role-scoped (``{"parties": [...]}``),
    links/categories flat (``"links"`` / ``"categories"``)."""

    @staticmethod
    def _admin() -> GeoPlaceAdmin:
        return GeoPlaceAdmin(GeoPlace, AdminSite())

    @staticmethod
    def _form(place: GeoPlace) -> MagicMock:
        form = MagicMock()
        form.instance = place
        return form

    @staticmethod
    def _formset(model: Any, changed: bool = True) -> MagicMock:
        formset = MagicMock()
        formset.model = model
        formset.has_changed.return_value = changed
        return formset

    @staticmethod
    def _party_rows(role_identifiers: list[str]) -> list[Any]:
        return [
            SimpleNamespace(role_id=role.pk, role=role)
            for role in (
                Category.objects.get(identifier=identifier)
                for identifier in role_identifiers
            )
        ]

    def _party_formset(
        self,
        *,
        changed: list[str] | None = None,
        new: list[str] | None = None,
        deleted: list[str] | None = None,
    ) -> MagicMock:
        """A changed GeoPlaceParty formset whose rows touch the given
        role identifiers (changed, newly added, and/or deleted)."""
        formset = self._formset(GeoPlaceParty)
        changed_roles: list[str] = changed or []
        new_roles: list[str] = new or []
        deleted_roles: list[str] = deleted or []
        changed_objects: list[tuple[Any, dict[str, Any]]] = [
            (row, {}) for row in self._party_rows(changed_roles)
        ]
        new_objects: list[Any] = list(self._party_rows(new_roles))
        deleted_objects: list[Any] = list(self._party_rows(deleted_roles))
        formset.changed_objects = changed_objects
        formset.new_objects = new_objects
        formset.deleted_objects = deleted_objects
        return formset

    def _save(self, place: GeoPlace, formset: MagicMock) -> None:
        self._admin().save_formset(
            request=MagicMock(), form=self._form(place), formset=formset, change=True
        )

    def test_party_formset_records_touched_roles(self):
        place = GeoPlaceFactory(is_modified=False)

        self._save(place, self._party_formset(changed=["role.brand"]))

        place.refresh_from_db()
        assert place.is_modified
        assert place.protected_party_roles() == {"role.brand"}

    def test_party_formset_merges_new_and_deleted_roles(self):
        place = GeoPlaceFactory(
            is_modified=False,
            protected_fields=[{"parties": ["role.operator"]}],
        )

        self._save(
            place, self._party_formset(new=["role.brand"], deleted=["role.source"])
        )

        place.refresh_from_db()
        assert place.protected_party_roles() == {
            "role.operator",
            "role.brand",
            "role.source",
        }

    def test_flat_parties_protection_is_kept(self):
        # Legacy flat entry (all roles) never narrows silently.
        place = GeoPlaceFactory(is_modified=False, protected_fields=["parties"])

        self._save(place, self._party_formset(changed=["role.brand"]))

        place.refresh_from_db()
        assert "parties" in (place.protected_fields or [])
        assert place.protected_party_roles() == set()

    def test_link_formset_marks_links_protected(self):
        place = GeoPlaceFactory(is_modified=False)

        self._save(place, self._formset(GeoPlaceExternalLink))

        place.refresh_from_db()
        assert place.is_modified
        assert "links" in (place.protected_fields or [])

    def test_category_formset_marks_categories_protected(self):
        place = GeoPlaceFactory(is_modified=False)

        self._save(place, self._formset(GeoPlaceCategory))

        place.refresh_from_db()
        assert "categories" in (place.protected_fields or [])

    def test_unchanged_formset_leaves_place_alone(self):
        place = GeoPlaceFactory(is_modified=False)

        self._save(place, self._formset(GeoPlaceParty, changed=False))

        place.refresh_from_db()
        assert not place.is_modified
        assert not (place.protected_fields or [])
