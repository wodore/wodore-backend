"""geoplace-kind-fk invariant tests (Opus review #8).

Pins the spec invariants at HTTP and ORM level:
- ``kind`` filter parity on search and nearby
- the ``kind`` member on nearby (batch path)
- batch anchor-association correctness: a sub-category that is
  another place's kind must not steal the anchor's classifier/extra
  (composite-key fix, review #2)
- ``classifier`` / ``extra`` on the ``kind`` member
- geonames derivation: m2m ``.add()`` never fires the rederive
  receiver (bulk_create sends no post_save), so the import command
  derives explicitly (review #3)
- the receiver's ``(order, slug)`` invariant across ORM writes
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from django.contrib.gis.geos import Point
from django.test import Client

from server.apps.categories.models import Category
from server.apps.external_geonames.models import GeoName
from server.apps.geometries.management.commands.import_geoplaces import Command
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory

pytestmark = pytest.mark.django_db

POINT = Point(7.75, 46.02, srid=4326)


def _child(parent_slug: str, slug: str, order: int) -> Category:
    parent = Category.objects.get(slug=parent_slug, parent__slug="amenity")
    cat, _ = Category.objects.get_or_create(
        slug=slug,
        parent=parent,
        defaults={"name": slug.replace("-", " ").title(), "order": order},
    )
    return cat


def _hut_cat() -> Category:
    return _child("accommodation", "kfx-hut", order=1)


def _shelter_cat() -> Category:
    return _child("accommodation", "kfx-shelter", order=2)


def _mode_classifier(slug: str) -> Category:
    return Category.objects.get_or_create(
        slug=slug, parent__slug="mode", defaults={"name": slug}
    )[0]


def _make_place(
    name: str, slug: str, category: Category, **assoc_kwargs: Any
) -> GeoPlace:
    place = GeoPlace.objects.create(
        name=name,
        slug=slug,
        location=POINT,
        country_code="CH",
        is_active=True,
        is_public=True,
        domain="amenity",
    )
    GeoPlaceCategory.objects.create(geo_place=place, category=category, **assoc_kwargs)
    return place


class TestKindFilter:
    def test_search_filter_by_identifier(self, client: Client) -> None:
        _make_place("Kindfx Alpha", "kfx-alpha", _hut_cat())
        _make_place("Kindfx Beta", "kfx-beta", _shelter_cat())
        response = client.get(
            "/v1/geo/places/search",
            {"q": "Kindfx", "kind": ["accommodation.kfx-hut"], "lang": "de"},
        )
        assert response.status_code == 200, response.content
        slugs = {entry["slug"] for entry in response.json()}
        assert slugs == {"kfx-alpha"}, response.content

    def test_search_filter_by_slug(self, client: Client) -> None:
        _make_place("Kindfx Gamma", "kfx-gamma", _hut_cat())
        _make_place("Kindfx Delta", "kfx-delta", _shelter_cat())
        response = client.get(
            "/v1/geo/places/search",
            {"q": "Kindfx", "kind": ["kfx-shelter"], "lang": "de"},
        )
        assert response.status_code == 200, response.content
        slugs = {entry["slug"] for entry in response.json()}
        assert slugs == {"kfx-delta"}, response.content

    def test_nearby_filter_by_identifier(self, client: Client) -> None:
        _make_place("Kindfx Epsilon", "kfx-epsilon", _hut_cat())
        _make_place("Kindfx Zeta", "kfx-zeta", _shelter_cat())
        response = client.get(
            "/v1/geo/places/nearby",
            {"lat": "46.02", "lon": "7.75", "kind": ["accommodation.kfx-hut"]},
        )
        assert response.status_code == 200
        slugs = {entry["slug"] for entry in response.json()}
        assert slugs == {"kfx-epsilon"}


class TestNearbyKindMember:
    def test_nearby_carries_kind(self, client: Client) -> None:
        _make_place("Kindfx Eta", "kfx-eta", _hut_cat())
        response = client.get(
            "/v1/geo/places/nearby",
            {"lat": "46.02", "lon": "7.75", "fields[places]": "slug,kind"},
        )
        assert response.status_code == 200
        entry = next(r for r in response.json() if r["slug"] == "kfx-eta")
        assert entry["kind"]["identifier"] == "accommodation.kfx-hut"
        assert entry["kind"]["slug"] == "kfx-hut"


class TestBatchAnchorAssoc:
    """Review #2: the anchor association must be the place's OWN
    (place, kind) association — never a sub-category association
    whose category happens to be another place's kind."""

    def test_subcategory_of_other_kind_does_not_steal_classifier(
        self, client: Client
    ) -> None:
        hut, shelter = _hut_cat(), _shelter_cat()
        standard, reduced = _mode_classifier("standard"), _mode_classifier("reduced")
        # Alpha: kind=hut (classifier standard) + sub shelter (reduced)
        alpha = _make_place("Kindfx Theta", "kfx-theta", hut, classifier=standard)
        GeoPlaceCategory.objects.create(
            geo_place=alpha, category=shelter, classifier=reduced
        )
        # Beta: kind=shelter — shelter is in the page's kind_ids set
        _make_place("Kindfx Iota", "kfx-iota", shelter, classifier=reduced)

        response = client.get(
            "/v1/geo/places/search",
            {"q": "Kindfx", "fields[places]": "slug,kind", "lang": "de"},
        )
        assert response.status_code == 200, response.content
        by_slug = {r["slug"]: r for r in response.json()}
        assert "kfx-theta" in by_slug, response.content
        # Alpha's classifier must come from its OWN hut association,
        # not the shelter association that matches Beta's kind
        assert by_slug["kfx-theta"]["kind"]["identifier"] == "accommodation.kfx-hut"
        assert by_slug["kfx-theta"]["kind"]["classifier"] == "mode.standard"
        assert by_slug["kfx-iota"]["kind"]["identifier"] == "accommodation.kfx-shelter"
        assert by_slug["kfx-iota"]["kind"]["classifier"] == "mode.reduced"


class TestKindMemberClassifierExtra:
    def test_kind_carries_classifier_and_extra(self, client: Client) -> None:
        _make_place(
            "Kindfx Kappa",
            "kfx-kappa",
            _hut_cat(),
            classifier=_mode_classifier("standard"),
            extra={"capacity": {"dormitory": 12}},
        )
        response = client.get(
            "/v1/geo/places/search",
            {"q": "Kindfx Kappa", "fields[places]": "slug,kind"},
        )
        assert response.status_code == 200
        kind = response.json()[0]["kind"]
        assert kind["classifier"] == "mode.standard"
        assert kind["extra"] == {"capacity": {"dormitory": 12}}


class TestGeonamesDerivation:
    """Review #3: ``categories.add()`` writes through bulk_create —
    no post_save fires, the rederive receiver never runs. The import
    command must derive the anchor explicitly."""

    @staticmethod
    def _geoname(category: Category) -> SimpleNamespace:
        return SimpleNamespace(
            geoname_id=48611,
            name="Kindfx Lambda",
            location=POINT,
            elevation=2200,
            country_code="CH",
            feature=SimpleNamespace(category=category, category_id=category.pk),
        )

    def test_create_place_derives_kind(self) -> None:
        # duck-typed stub: _create_place only reads attributes, no
        # GeoName persistence is involved — cast states that contract
        geoname = cast(GeoName, self._geoname(_hut_cat()))
        place = Command()._create_place(geoname, 5)
        place.refresh_from_db()
        assert place.kind_id == _hut_cat().pk
        assert place.domain == "amenity"

    def test_update_place_derives_kind(self) -> None:
        place = GeoPlace.objects.create(
            name="Kindfx Mu",
            slug="kfx-mu",
            location=POINT,
            country_code="CH",
            is_active=True,
            is_public=True,
        )
        updated = Command()._update_place(
            place, cast(GeoName, self._geoname(_hut_cat())), 5
        )
        assert updated is True
        place.refresh_from_db()
        assert place.kind_id == _hut_cat().pk
        assert place.domain == "amenity"


class TestReceiverInvariant:
    def test_kind_follows_order_slug_on_orm_writes(self) -> None:
        place = GeoPlace.objects.create(
            name="Kindfx Nu",
            slug="kfx-nu",
            location=POINT,
            country_code="CH",
            is_active=True,
            is_public=True,
        )
        hut, shelter = _hut_cat(), _shelter_cat()
        assoc_hut = GeoPlaceCategory.objects.create(geo_place=place, category=hut)
        place.refresh_from_db()
        assert place.kind_id == hut.pk  # single association anchors

        assoc_shelter = GeoPlaceCategory.objects.create(
            geo_place=place, category=shelter
        )
        place.refresh_from_db()
        assert place.kind_id == hut.pk  # (order, slug): hut sorts first

        assoc_hut.delete()
        place.refresh_from_db()
        assert place.kind_id == shelter.pk  # anchor re-derives on delete

        assoc_shelter.delete()
        place.refresh_from_db()
        assert place.kind_id is None  # no categories — no kind
