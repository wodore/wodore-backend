"""New-capability tests: provider merge, replies, merge requests."""

import datetime
import typing as t
from typing import Any

import pytest

from django.test import Client

from server.apps.accounts.models import User
from server.apps.reviews import services
from server.apps.reviews.models import ReviewMergeRequest, SubmittedReview
from server.apps.reviews.refuges_info import RefugeComment
from server.apps.reviews.services import subject_for_hut

from .conftest import review_item

pytestmark = pytest.mark.django_db


def _user(email: str = "replier@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


def _logged_in_client() -> tuple[Client, User]:
    user = _user()
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client, user


def _comment(comment_id: str, author: str, days_ago: int, text: str) -> RefugeComment:
    return RefugeComment(
        signature=f"refuges-info:{comment_id}",
        author=author,
        created=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        + datetime.timedelta(days=days_ago),
        text=text,
    )


class TestProviderMerge:
    def test_refuges_comments_merged_with_source_and_license(
        self, hut: Any, use_fake_client: Any, fake_refuges: Any
    ) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature="mg-1", subject=subject, iat=1_500_000_000)
        ]
        fake_refuges.comments = [
            _comment("9001", "annie", 1, "Belle cabane, gardien sympa"),
            _comment("9002", "bob", 2, "Accueil chaleureux & bon repas"),
        ]
        envelope = services.list_reviews(hut, limit=20, offset=0)
        by_signature = {r.signature: r for r in envelope.data}
        assert set(by_signature) == {"mg-1", "refuges-info:9001", "refuges-info:9002"}
        refuge = by_signature["refuges-info:9001"]
        assert refuge.source == "refuges.info"
        assert refuge.license == "CC BY-SA 2.0 FR"
        assert refuge.link and refuge.link.endswith("/point/3760")
        assert refuge.nickname == "annie"
        assert refuge.opinion == "Belle cabane, gardien sympa"
        assert refuge.rating is None
        # Mangrove item carries its own license and no link.
        assert by_signature["mg-1"].source == "open_reviews"
        assert by_signature["mg-1"].license == "CC-BY-4.0"
        # HTML-free text passes through verbatim.
        assert (
            by_signature["refuges-info:9002"].opinion
            == "Accueil chaleureux & bon repas"
        )

    @pytest.mark.usefixtures("use_fake_client")
    def test_blacklist_hides_provider_comments(
        self, hut: Any, fake_refuges: Any
    ) -> None:
        from .conftest import blacklist

        fake_refuges.comments = [_comment("9003", "x", 1, "spam")]
        blacklist("refuges-info:9003")
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert envelope.count == 0

    def test_provider_failure_degrades_to_mangrove_only(
        self, hut: Any, use_fake_client: Any, fake_refuges: Any
    ) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="mg-2", subject=subject)]
        fake_refuges.fail = True
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert [r.signature for r in envelope.data] == ["mg-2"]

    def test_summary_counts_merged_sources(
        self, hut: Any, use_fake_client: Any, fake_refuges: Any
    ) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature="mg-3", subject=subject, rating=80)
        ]
        fake_refuges.comments = [_comment("9004", "y", 1, "ok")]
        summary = services.summary_for_hut(hut)
        assert summary.count == 2
        assert summary.rating_count == 1
        assert summary.rating_mean == 80.0

    @pytest.mark.usefixtures("use_fake_client")
    def test_provider_respects_kill_switch(self, hut: Any, fake_refuges: Any) -> None:
        from django.test import override_settings

        fake_refuges.comments = [_comment("9005", "z", 1, "hidden")]
        with override_settings(ORA_REFUGES_INFO_ENABLED=False):
            envelope = services.list_reviews(hut, limit=20, offset=0)
        assert envelope.count == 0
        assert fake_refuges.calls == []  # never consulted


class TestRefugesParsing:
    """Unit tests for the raw→parsed comment cleaning (real client)."""

    def test_clean_text_unescapes_and_strips(self) -> None:
        from server.apps.reviews.refuges_info import _clean_text

        assert _clean_text("<b>Accueil</b> chaleureux &amp; bon repas") == (
            "Accueil chaleureux & bon repas"
        )
        assert _clean_text("  a<br/>\nb ") == "a b"

    def test_parse_date_tolerant(self) -> None:
        from server.apps.reviews.refuges_info import _parse_date

        parsed = _parse_date("2026-08-16 18:14:02.018925+02")
        # Tolerant of the bare ±HH offset AND normalized to UTC
        # (18:14+02 → 16:14 UTC) for sort-stable ISO strings.
        assert parsed == datetime.datetime(
            2026, 8, 16, 16, 14, 2, 18925, tzinfo=datetime.UTC
        )
        assert _parse_date("2026-08-16 18:14:02+00:00") is not None
        assert _parse_date("garbage") is None

    def test_parse_dict_by_index_and_list(self) -> None:
        from server.apps.reviews.refuges_info import parse_comments

        payload = {
            "copyright": "CC By-Sa 2.0",
            "0": {
                "id_commentaire": "1",
                "texte_commentaire": "second",
                "date_commentaire": "2026-02-01 10:00:00+01",
            },
            "1": {
                "id_commentaire": "2",
                "texte_commentaire": "first",
                "date_commentaire": "2026-01-01 10:00:00+01",
            },
        }
        comments = parse_comments(payload)
        assert [c.signature for c in comments] == ["refuges-info:2", "refuges-info:1"]
        assert parse_comments([payload["0"]])[0].signature == "refuges-info:1"


class TestReplies:
    def test_reply_and_list_replies(self, hut: Any, use_fake_client: Any) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        parent = review_item(signature="parent-1", subject=subject)
        use_fake_client.items = [parent]

        created = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-1/reply",
            {"opinion": "thanks for the details"},
            content_type="application/json",
        )
        assert created.status_code == 201, created.content
        # The reply was signed against the maresi subject of the parent.
        reply_jwt = use_fake_client.submitted[-1]
        payload = _payload(reply_jwt)
        assert payload["sub"] == "urn:maresi:parent-1"
        assert payload["opinion"] == "thanks for the details"
        row = SubmittedReview.objects.get(signature=created.json()["signature"])
        assert row.target_signature == "parent-1"

        # The replies endpoint lists upstream replies (fake kid listing).
        use_fake_client.kid_items = [
            review_item(
                signature="reply-x",
                subject="urn:maresi:parent-1",
                opinion="me too",
            )
        ]
        listing = client.get(f"/v1/huts/{hut.slug}/reviews/parent-1/replies")
        assert listing.status_code == 200
        served = [r["signature"] for r in listing.json()["data"]]
        # The upstream reply (reply-x) AND our just-written reply (overlay).
        assert "reply-x" in served
        assert created.json()["signature"] in served

    def test_reply_requires_rating_or_opinion(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="parent-2", subject=subject)]
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-2/reply",
            {},
            content_type="application/json",
        )
        assert response.status_code == 400

    @pytest.mark.usefixtures("use_fake_client")
    def test_reply_to_foreign_hut_review_404(self, hut: Any) -> None:
        client, user = _logged_in_client()
        from .conftest import log_row

        log_row(user, "otherhut", "geo:0,0?q=otherhut&u=30", "parent-3")
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-3/reply",
            {"opinion": "hi"},
            content_type="application/json",
        )
        assert response.status_code == 404


class TestMergeRequest:
    @pytest.mark.usefixtures("use_fake_client")
    def test_create_and_queue(self, hut: Any) -> None:
        client, user = _logged_in_client()
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/merge-request",
            {
                "target": "geo:46.5,8.0?q=Mont+Fort&u=30",
                "note": "same hut, OSM name variant",
                "link": "https://www.camptocamp.org/waypoints/114649",
            },
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["state"] == "new"
        row = ReviewMergeRequest.objects.get(pk=body["id"])
        assert row.hut == hut
        assert row.created_by == user
        assert "camptocamp" in row.link

    @pytest.mark.usefixtures("use_fake_client")
    def test_requires_target(self, hut: Any) -> None:
        client, _user = _logged_in_client()
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/merge-request",
            {"note": "no target"},
            content_type="application/json",
        )
        assert response.status_code == 400


def _payload(jwt: str) -> dict[str, t.Any]:
    import base64
    import json

    part = jwt.split(".")[1]
    return t.cast(
        dict[str, t.Any],
        json.loads(base64.urlsafe_b64decode(part + "=" * ((4 - len(part) % 4) % 4))),
    )
