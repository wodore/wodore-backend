"""MangroveClient unit + contract tests (specs: mangrove-client)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from django.test import override_settings

from server.apps.reviews import client as reviews_client
from server.apps.reviews import services
from server.apps.reviews.client import (
    MangroveClient,
    UpstreamRejected,
    UpstreamUnavailable,
    normalize_q,
    parse_geo_subject,
    subject_geo_matches,
)

pytestmark = pytest.mark.django_db

BASE = "https://mangrove.test"


class TestSubjectRecipe:
    def test_recipe_is_pure_and_stable(self, hut: Any) -> None:
        first = services.subject_for_hut(hut)
        second = services.subject_for_hut(hut)
        assert first == second
        assert first.startswith("geo:")
        assert "?q=" in first and "&u=30" in first

    def test_q_is_the_osm_name_before_any_review(self, hut: Any) -> None:
        # OSM name (current HutSource, org osm) wins until a review pins.
        assert "q=OSM+Hut+Name" in services.subject_for_hut(hut)

    def test_q_falls_back_to_hut_name_without_osm(self, hut: Any) -> None:
        from server.apps.huts.models import HutSource

        HutSource.objects.filter(hut=hut, organization__slug="osm").update(
            is_current=False
        )
        assert f"q={hut.name.replace(' ', '+')}" in services.subject_for_hut(hut)

    def test_first_review_pins_the_name(self, hut: Any, use_fake_client: Any) -> None:
        from server.apps.accounts.models import User
        from server.apps.reviews.models import HutReviewSubject
        from server.apps.reviews.schemas import ReviewSubmitIn

        user = User.objects.create_user(email="p@y.z", password="x")  # type: ignore  # custom manager/queryset inference gap
        before = services.subject_for_hut(hut)
        services.submit_review(
            user, hut, ReviewSubmitIn.model_validate({"rating": 50}), "de"
        )
        assert HutReviewSubject.objects.filter(hut=hut, name="OSM Hut Name").exists()
        assert services.subject_for_hut(hut) == before  # same name, now pinned

    def test_pinned_name_survives_osm_rename(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        from server.apps.huts.models import HutSource
        from server.apps.reviews.models import HutReviewSubject

        HutReviewSubject.objects.create(hut=hut, name="OSM Hut Name")
        HutSource.objects.filter(hut=hut, organization__slug="osm").update(
            name="Renamed on OSM"
        )
        assert "q=OSM+Hut+Name" in services.subject_for_hut(hut)

    def test_normalized_q_uniqueness_lemma(self) -> None:
        # Two review names that differ only by punctuation normalize equal
        # — nearby huts sharing them would share reviews (accepted trade-off).
        assert normalize_q("alpe-x") == normalize_q("alpex")
        assert normalize_q("Alpe X") == normalize_q("alpex")
        assert normalize_q("café") == normalize_q("cafe")


class TestGeoMatch:
    REF = "geo:46.500000,8.000000?q=testhut&u=30"

    def test_same_q_within_radius_matches(self) -> None:
        assert subject_geo_matches("geo:46.500100,8.000000?q=testhut&u=30", self.REF)

    def test_case_and_punctuation_normalized(self) -> None:
        assert subject_geo_matches("geo:46.500100,8.000000?q=Test.Hut&u=30", self.REF)

    def test_different_q_never_matches(self) -> None:
        assert not subject_geo_matches(
            "geo:46.500000,8.000000?q=otherhut&u=500", self.REF
        )

    def test_distance_beyond_u_sum_rejected(self) -> None:
        assert not subject_geo_matches(
            "geo:46.510000,8.000000?q=testhut&u=30", self.REF
        )

    def test_q_less_subject_rejected_by_local_filter(self) -> None:
        assert not subject_geo_matches("geo:46.500000,8.000000&u=100", self.REF)

    def test_non_geo_subject_rejected(self) -> None:
        assert not subject_geo_matches("https://example.com", self.REF)
        assert parse_geo_subject("https://example.com") is None


class TestClientResilience:
    @respx.mock
    def test_get_retries_within_budget(self) -> None:
        route = respx.get(f"{BASE}/reviews").mock(
            side_effect=[
                httpx.ConnectError("blip"),
                httpx.Response(200, json={"reviews": []}),
            ]
        )
        response = MangroveClient(base_url=BASE).list_reviews("geo:0,0?q=T&u=10")
        assert response.reviews == []
        assert route.call_count == 2

    @respx.mock
    def test_get_retry_budget_exhausted(self) -> None:
        respx.get(f"{BASE}/reviews").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(UpstreamUnavailable):
            MangroveClient(base_url=BASE).list_reviews("geo:0,0?q=T&u=10")

    @respx.mock
    @override_settings(MANGROVE_GET_RETRIES=2)
    def test_submit_never_retries(self) -> None:
        route = respx.post(f"{BASE}/submit").mock(side_effect=httpx.ConnectError("x"))
        with pytest.raises(UpstreamUnavailable):
            MangroveClient(base_url=BASE).submit("a.b.c")
        assert route.call_count == 1  # fail fast — never re-submit

    @respx.mock
    def test_upstream_500_maps_to_unavailable(self) -> None:
        respx.get(f"{BASE}/reviews").mock(return_value=httpx.Response(500, text="boom"))
        with pytest.raises(UpstreamUnavailable):
            MangroveClient(base_url=BASE).list_reviews("geo:0,0?q=T&u=10")

    @respx.mock
    def test_upstream_4xx_maps_to_rejected(self) -> None:
        respx.post(f"{BASE}/submit").mock(
            return_value=httpx.Response(400, text="Incorrect JWT: bad key")
        )
        with pytest.raises(UpstreamRejected) as excinfo:
            MangroveClient(base_url=BASE).submit("a.b.c")
        assert "bad key" in str(excinfo.value.detail)

    @respx.mock
    def test_drifted_payload_maps_to_unavailable(self) -> None:
        respx.get(f"{BASE}/reviews").mock(
            return_value=httpx.Response(200, json={"unexpected": True})
        )
        with pytest.raises(UpstreamUnavailable):
            MangroveClient(base_url=BASE).list_reviews("geo:0,0?q=T&u=10")


class TestContractFixtures:
    """The recorded 0.4.1 fixtures must parse through the pinned models."""

    FIXTURES = Path("server/apps/reviews/fixtures/mangrove")

    def test_reviews_list_fixture_parses(self) -> None:
        data = json.loads((self.FIXTURES / "reviews_list.json").read_text())
        parsed = reviews_client.ReviewsResponse.model_validate(data["body"])
        assert len(parsed.reviews) > 0
        assert all(item.signature and item.jwt and item.kid for item in parsed.reviews)

    def test_review_by_signature_fixture_parses(self) -> None:
        data = json.loads((self.FIXTURES / "review_by_signature.json").read_text())
        parsed = reviews_client.ReviewItem.model_validate(data["body"])
        assert parsed.payload.sub.startswith("geo:0,0")

    def test_issuer_fixture_parses(self) -> None:
        data = json.loads((self.FIXTURES / "issuer.json").read_text())
        parsed = reviews_client.IssuerStats.model_validate(data["body"])
        assert parsed.count >= 0

    def test_subject_aggregate_fixture_parses(self) -> None:
        data = json.loads((self.FIXTURES / "subject_aggregate.json").read_text())
        parsed = reviews_client.SubjectAggregate.model_validate(data["body"])
        assert parsed.sub.startswith("geo:0,0")

    def test_fixture_note_documents_submit_response(self) -> None:
        data = json.loads((self.FIXTURES / "submit_response.json").read_text())
        assert data["body"] is True  # literal `true`, no signature
