"""HTTP-level tests for the unified slug-keyed place detail endpoint
(place-detail-endpoint) and the places-family slug-only identifier policy.
"""

from __future__ import annotations

import re

import pytest

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client

from server.apps.categories.models import Category
from server.apps.geometries.converters import SLUG_GRAMMAR_RE
from server.apps.geometries.models import GeoPlace, GeoPlaceParty
from server.apps.parties.models import Party

pytestmark = [pytest.mark.django_db]


def make_place(**overrides: object) -> GeoPlace:
    """Create an active+public place; save() mints a grammar-conforming slug."""
    defaults: dict[str, object] = {
        "name": "Test Berg",
        "location": Point(7.65, 45.98, srid=4326),
        "country_code": "CH",
        "is_active": True,
        "is_public": True,
    }
    defaults.update(overrides)
    return GeoPlace.objects.create(**defaults)  # type: ignore[arg-type]


def make_operation(place) -> None:  # type: ignore[no-untyped-def]
    """Create a standard-mode operation (the amenity block's new source)."""
    from server.apps.categories.models import Category
    from server.apps.geometries.models import GeoPlaceOperation

    mode_standard = Category.objects.get(slug="standard", parent__slug="mode")
    GeoPlaceOperation.objects.get_or_create(
        geo_place=place,
        mode=mode_standard,
        defaults={"capacity": None, "opening_hours": {}},
    )


class TestSlugGrammar:
    def test_minted_slugs_match_grammar(self):
        place = make_place()
        assert place.slug
        assert re.fullmatch(SLUG_GRAMMAR_RE, place.slug)
        assert "-" in place.slug  # {base}-{random suffix}

    def test_clean_rejects_pure_word_slug(self):
        place = GeoPlace(slug="zermatt")
        with pytest.raises(ValidationError, match="at least one"):
            place.clean_slug()

    def test_clean_rejects_reserved_slug(self):
        place = GeoPlace(slug="search")
        with pytest.raises(ValidationError, match="reserved"):
            place.clean_slug()

    @pytest.mark.parametrize(
        "legacy_slug",
        ["vending_machine", "drinking_water-", "information-5h9"],
    )
    def test_clean_accepts_legacy_shapes(self, legacy_slug: str):
        GeoPlace(slug=legacy_slug).clean_slug()  # no raise

    def test_constraint_rejects_invalid_slug_on_direct_save(self):
        """save() bypasses clean() — the check constraint is the guarantee."""
        place = make_place()
        place.slug = "zermatt"
        with pytest.raises(IntegrityError), transaction.atomic():
            place.save(update_fields=["slug"])


class TestPlaceDetailRouting:
    def test_fixed_segments_are_never_captured_as_slugs(self, client: Client):
        # Order-independent by grammar: search/nearby/overlays cannot
        # match the <geoplace:slug> converter.
        assert (
            client.get("/v1/geo/places/search", {"q": "zz-none-zz"}).status_code == 200
        )
        assert client.get("/v1/geo/places/overlays").status_code == 200

    def test_detail_by_slug(self, client: Client):
        place = make_place()
        response = client.get(f"/v1/geo/places/{place.slug}")
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == place.slug
        assert data["name"] == "Test Berg"
        assert data["kind_slug"] == "none"
        assert "id" not in data
        assert "public, max-age=60" in response.headers["Cache-Control"]

    def test_legacy_slug_shapes_resolve(self, client: Client):
        place = make_place()
        place.slug = "vending_machine"
        place.save(update_fields=["slug"])
        assert client.get("/v1/geo/places/vending_machine").status_code == 200

    def test_unknown_slug_answers_standard_404(self, client: Client):
        response = client.get("/v1/geo/places/zz-none-aaaaa")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "not_found"
        # RFC 9457 problem members per the single error contract.
        assert body["status"] == 404
        assert body["type"]
        assert body["title"]
        assert body["instance"]

    def test_hidden_place_indistinguishable_from_missing(self, client: Client):
        place = make_place(is_public=False)
        hidden = client.get(f"/v1/geo/places/{place.slug}")
        unknown = client.get("/v1/geo/places/zz-none-aaaaa")
        assert hidden.status_code == unknown.status_code == 404
        # The RFC 9457 `instance` member names the requested path (which
        # the client knows anyway); everything else must be identical.
        hidden_body, unknown_body = hidden.json(), unknown.json()
        hidden_body.pop("instance")
        unknown_body.pop("instance")
        assert hidden_body == unknown_body
        assert hidden.json()["code"] == "not_found"

    def test_inactive_place_404(self, client: Client):
        place = make_place(is_active=False)
        assert client.get(f"/v1/geo/places/{place.slug}").status_code == 404

    def test_removed_amenity_route_is_gone(self, client: Client):
        assert client.get("/v1/geo/places/amenity/123").status_code == 404


class TestPlaceDetailContent:
    def test_amenity_place_carries_block(self, client: Client):
        place = make_place(kind_slug="map.amenity")
        make_operation(place)
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert data["kind_slug"] == "map.amenity"
        assert data["amenity"]["operating_status"] == "open"
        assert set(data["amenity"]) == {
            "operating_status",
            "opening_months",
            "opening_hours",
        }
        assert "phones" not in data["amenity"]  # retired: uri.phone links
        assert data["description"] == ""
        assert data["review_status"] in {"new", "review", "rework", "done"}

    def test_amenity_type_without_detail_row_has_no_block(self, client: Client):
        place = make_place(kind_slug="map.amenity")
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert "amenity" not in data

    def test_place_without_detail_model_is_first_class(self, client: Client):
        place = make_place(kind_slug="map.natural")
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert data["kind_slug"] == "map.natural"
        assert "amenity" not in data

    def test_default_response_carries_categories(
        self, seed_data: dict[str, int], client: Client
    ):
        place = (
            GeoPlace.objects.filter(is_active=True, is_public=True)
            .exclude(categories=None)
            .first()
        )
        assert place is not None
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert data["categories"]

    def test_narrowed_selection(self, client: Client):
        place = make_place(kind_slug="map.amenity")
        make_operation(place)
        data = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,name,amenity"},
        ).json()
        # Selected + required members only.
        assert set(data) == {
            "slug",
            "name",
            "amenity",
            "kind_slug",
            "location",
            "importance",
        }
        assert data["amenity"]["operating_status"] == "open"

    def test_block_of_another_type_absent_not_error(self, client: Client):
        place = make_place(kind_slug="map.natural")
        response = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,name,amenity"},
        )
        assert response.status_code == 200
        assert "amenity" not in response.json()

    def test_unknown_block_name_400_naming_valid_fields(self, client: Client):
        place = make_place()
        response = client.get(
            f"/v1/geo/places/{place.slug}", {"fields[places]": "admin"}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "amenity" in body["detail"]  # valid names listed

    def test_selecting_empty_members_is_200_with_member_absent(self, client: Client):
        """Review finding #1: selection validity comes from the schema,
        not from what the row carries — no spurious 400 on empty members."""
        place = make_place()  # no categories/sources/parties, no amenity
        response = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,name,categories,sources,parties,amenity"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "categories" not in data
        assert "sources" not in data
        assert "parties" not in data
        assert "amenity" not in data

    def test_nested_category_narrowing_keeps_required(
        self, seed_data: dict[str, int], client: Client
    ):
        """Review finding #2: nested required fields stay (no pydantic 500)."""
        place = (
            GeoPlace.objects.filter(is_active=True, is_public=True)
            .exclude(categories=None)
            .first()
        )
        assert place is not None
        data = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,categories", "fields[categories]": "slug"},
        ).json()
        assert data["categories"]
        for category in data["categories"]:
            assert "slug" in category
            assert "name" in category  # required member kept

    def test_nested_parties_narrowing(self, client: Client):
        """Review finding #3: fields[parties] narrows on the detail route."""
        place = make_place()
        party = Party.objects.create(slug="test-club", name="Test Club")
        role = Category.objects.get(slug="operator", parent__slug="role")
        GeoPlaceParty.objects.create(geo_place=place, party=party, role=role)
        data = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,parties", "fields[parties]": "slug"},
        ).json()
        assert len(data["parties"]) == 1
        assert "slug" in data["parties"][0]
        assert "role" in data["parties"][0]  # required member kept

    def test_lang_variants_cache_separately(self, client: Client):
        """Task 5.5: language variants must never mix through cache_page."""
        place = make_place(name="Test Berg", name_fr="Test Montagne")
        default = client.get(f"/v1/geo/places/{place.slug}")
        french = client.get(f"/v1/geo/places/{place.slug}", {"lang": "fr"})
        default_again = client.get(f"/v1/geo/places/{place.slug}")
        assert default.json()["name"] == "Test Berg"
        assert french.json()["name"] == "Test Montagne"
        assert default_again.json()["name"] == "Test Berg"


class TestPlaceLinks:
    """The links member (external-link-uris): typed external links on
    the place detail response, sibling of categories/sources/parties."""

    def _link_place(self, place: GeoPlace) -> None:
        from server.apps.external_links.models import ExternalLink
        from server.apps.geometries.models import GeoPlaceExternalLink

        link = ExternalLink(url="tel:+41441234567", label="Reception")
        link.save()  # derives uri.phone
        GeoPlaceExternalLink.objects.create(
            geo_place=place, external_link=link, order=0
        )

    def test_detail_carries_links(self, client: Client):
        place = make_place()
        self._link_place(place)
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert len(data["links"]) == 1
        link = data["links"][0]
        assert link["uri"] == "uri.phone"
        assert link["url"] == "tel:+41441234567"
        assert link["label"] == "Reception"
        assert link["symbol"]  # kind icon resolves

    def test_phones_served_under_links_not_block(self, client: Client):
        place = make_place(kind_slug="map.amenity")
        make_operation(place)
        self._link_place(place)
        data = client.get(f"/v1/geo/places/{place.slug}").json()
        assert "phones" not in data["amenity"]
        assert data["links"][0]["uri"] == "uri.phone"

    def test_narrowed_selection_skips_links(self, client: Client):
        place = make_place()
        self._link_place(place)
        data = client.get(
            f"/v1/geo/places/{place.slug}", {"fields[places]": "slug,name"}
        ).json()
        assert "links" not in data

    def test_nested_links_narrowing_keeps_required(self, client: Client):
        place = make_place()
        self._link_place(place)
        data = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,links", "fields[links]": "uri"},
        ).json()
        link = data["links"][0]
        assert "uri" in link and "url" in link  # url is required, kept

    def test_selecting_links_on_linkless_place_is_200(self, client: Client):
        place = make_place()
        response = client.get(
            f"/v1/geo/places/{place.slug}",
            {"fields[places]": "slug,name,links"},
        )
        assert response.status_code == 200
        assert "links" not in response.json()


class TestSlugOnlyIdentifiers:
    def test_search_results_carry_slug_not_id(
        self, seed_data: dict[str, int], client: Client
    ):
        results = client.get("/v1/geo/places/search", {"q": "Dammastock"}).json()
        assert isinstance(results, list)
        for item in results:
            assert "slug" in item
            assert "id" not in item

    def test_nearby_results_carry_slug_not_id(
        self, seed_data: dict[str, int], client: Client
    ):
        results = client.get(
            "/v1/geo/places/nearby", {"lat": "46.5", "lon": "8.4", "radius": "30000"}
        ).json()
        assert isinstance(results, list)
        for item in results:
            assert "slug" in item
            assert "id" not in item

    def test_list_results_navigate_to_detail(
        self, seed_data: dict[str, int], client: Client
    ):
        results = client.get("/v1/geo/places/search", {"q": "Dammastock"}).json()
        for item in results:
            detail = client.get(f"/v1/geo/places/{item['slug']}")
            assert detail.status_code == 200
            assert detail.json()["slug"] == item["slug"]
            break
