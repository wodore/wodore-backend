"""Opus-review fix tests: overlay visibility, edit rows, q encoding, guards."""

import json
import typing as t
from pathlib import Path
from typing import Any

import pytest

from django.test import Client

from server.apps.accounts.models import User
from server.apps.reviews import services
from server.apps.reviews.client import ReviewImagePayload, subject_geo_matches
from server.apps.reviews.schemas import ReviewSubmitIn
from server.apps.reviews.services import build_geo_subject, subject_for_hut

from .conftest import log_row, review_item

pytestmark = pytest.mark.django_db

FIXTURES = Path("server/apps/reviews/fixtures/mangrove")


def _user(email: str = "fix@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


class TestOverlayVisibility:
    """B1: own writes visible regardless of cache state / worker / lag."""

    def test_cold_cache_submit_visible_despite_upstream_lag(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        """The fake upstream does NOT list the new review (lag) — the
        overlay from the submission log still shows it, cold cache."""
        user = _user()
        use_fake_client.items.clear()  # upstream lags: nothing listed yet
        out = services.submit_review(
            user, hut, ReviewSubmitIn.model_validate({"rating": 70}), "de"
        )
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert any(r.signature == out.signature for r in envelope.data)

    def test_delete_hidden_despite_upstream_lag(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        """Upstream still lists the review (lag) — the overlay drops it."""
        from django.core.cache import caches

        caches["shared"].clear()  # force fresh state
        user = _user()
        out = services.submit_review(
            user, hut, ReviewSubmitIn.model_validate({"rating": 70}), "de"
        )
        # Upstream "caught up": lists the review now.
        use_fake_client.items = [
            review_item(signature=out.signature, subject=subject_for_hut(hut))
        ]
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert any(r.signature == out.signature for r in envelope.data)
        services.delete_review(user, hut, out.signature)
        # Upstream still lists it (lag) — overlay must hide it.
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert not any(r.signature == out.signature for r in envelope.data)

    def test_edit_patched_despite_upstream_lag(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        user = _user()
        out = services.submit_review(
            user, hut, ReviewSubmitIn.model_validate({"rating": 10}), "de"
        )
        use_fake_client.items = [
            review_item(
                signature=out.signature, subject=subject_for_hut(hut), rating=10
            )
        ]
        from server.apps.reviews.schemas import ReviewEditIn

        services.edit_review(
            user,
            hut,
            out.signature,
            ReviewEditIn.model_validate({"rating": 95}),
        )
        envelope = services.list_reviews(hut, limit=20, offset=0)
        review = next(r for r in envelope.data if r.signature == out.signature)
        assert review.rating == 95


class TestEditRowsUpstream:
    """B3: upstream serves the EDIT row — identity stays stable."""

    def test_edit_row_kept_with_stable_signature_and_geo_match(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        subject = subject_for_hut(hut)
        original_sub = subject
        edited = review_item(
            signature="edit-row-sig",
            subject="urn:maresi:original-sig",
            rating=90,
            opinion="edited text",
        )
        edited = edited.model_copy(update={"original_sub": original_sub})
        edited.payload.action = "edit"
        use_fake_client.items = [edited]
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert envelope.count == 1
        served = envelope.data[0]
        # Stable identity: the ORIGINAL signature, not the edit row's.
        assert served.signature == "original-sig"
        assert served.rating == 90

    def test_edited_blacklisted_original_stays_hidden(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        from .conftest import blacklist

        subject = subject_for_hut(hut)
        edited = review_item(
            signature="edit-row-sig2", subject="urn:maresi:orig-sig2", rating=50
        )
        edited = edited.model_copy(update={"original_sub": subject})
        edited.payload.action = "edit"
        use_fake_client.items = [edited]
        # Blacklisting the ORIGINAL signature must hide the edit too.
        blacklist("orig-sig2")
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert envelope.count == 0

    def test_edited_fixture_contract(self) -> None:
        """The recorded 0.4.1 fixture: default listings serve edit rows."""
        from server.apps.reviews.client import ReviewItem

        data = json.loads((FIXTURES / "reviews_list_edited.json").read_text())
        parsed = [ReviewItem.model_validate(item) for item in data["body"]["reviews"]]
        assert parsed, "fixture must contain the edit row"
        edit_rows = [i for i in parsed if i.payload.action == "edit"]
        assert edit_rows
        row = edit_rows[0]
        assert row.original_sub and row.original_sub.startswith("geo:")
        assert row.payload.sub.startswith("urn:maresi:")
        assert row.payload.sub.removeprefix("urn:maresi:") != row.signature


class TestQEncoding:
    """B4: plus-encoded spaces, percent-encoded accents (probe 2026-11-08)."""

    def test_spaces_encode_as_plus(self) -> None:
        assert build_geo_subject(1.0, 2.0, "OSM Hut Name") == (
            "geo:1.000000,2.000000?q=OSM+Hut+Name&u=30"
        )

    def test_accents_percent_encoded_utf8(self) -> None:
        subject = build_geo_subject(1.0, 2.0, "café-hut")
        assert "q=caf%C3%A9-hut" in subject

    def test_matching_decodes_both_forms(self) -> None:
        assert subject_geo_matches(
            "geo:1.000000,2.000000?q=OSM+Hut+Name&u=30",
            "geo:1.000000,2.000000?q=OSM%20Hut%20Name&u=30",
        )


class TestImageSrcStrictness:
    """B7: parser-confusion bypasses rejected."""

    def test_bypasses_rejected(self, hut: Any, use_fake_client: Any) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(
                signature="bypass",
                subject=subject,
                images=[
                    ReviewImagePayload(
                        src="https://evil.com\\@files.mangrove.reviews/x"
                    ),
                    ReviewImagePayload(src="https://files.mangrove.reviews:8443/x"),
                    ReviewImagePayload(src="https://files.mangrove.reviews/x?a=b#c"),
                ],
            )
        ]
        envelope = services.list_reviews(hut, limit=10, offset=0)
        # The query-string one is legit; the other two must be dropped.
        assert [i.src for i in envelope.data[0].images] == [
            "https://files.mangrove.reviews/x?a=b#c"
        ]


class TestUpstreamFailureGuards:
    """B2: upstream failures surface as 503, never 500."""

    def test_edit_upstream_down_503_not_500(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services as services_module

        subject = subject_for_hut(hut)
        user = _user()
        services.submit_review(
            user, hut, ReviewSubmitIn.model_validate({"rating": 40}), "de"
        )
        # Now make the ownership fallback path fail: user WITHOUT a key
        # targets a foreign review (forces the upstream kid comparison).
        stranger = _user("stranger@example.com")
        log_row(stranger, hut.slug, subject, "foreign-down-sig")
        monkeypatch.setattr(services_module, "_client", _DownClient(fake_client))
        client = Client(SERVER_NAME="localhost")
        client.force_login(stranger)
        response = client.post(f"/v1/huts/{hut.slug}/reviews/foreign-down-sig/delete")
        assert response.status_code == 503
        assert response.json()["code"] == "service_unavailable"

    def test_my_reviews_upstream_down_503(
        self, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services as services_module

        user = _user("mine@example.com")
        hut_key = services.get_or_mint_key(user)  # flow must reach upstream
        assert hut_key is not None
        monkeypatch.setattr(services_module, "_client", _DownClient(fake_client))
        client = Client(SERVER_NAME="localhost")
        client.force_login(user)
        response = client.get("/v1/my/reviews")
        assert response.status_code == 503


class _DownClient:
    """Every upstream call fails as unavailable."""

    def __init__(self, inner: t.Any) -> None:
        self.inner = inner

    def list_reviews(self, _subject: str) -> t.Any:
        from server.apps.reviews.client import UpstreamUnavailable

        raise UpstreamUnavailable("down")

    def list_reviews_by_kid(self, _kid: str) -> t.Any:
        from server.apps.reviews.client import UpstreamUnavailable

        raise UpstreamUnavailable("down")

    def review(self, _signature: str) -> t.Any:
        from server.apps.reviews.client import UpstreamUnavailable

        raise UpstreamUnavailable("down")

    def submit(self, jwt: str) -> None:
        return self.inner.submit(jwt)

    def __getattr__(self, name: str) -> t.Any:
        return getattr(self.inner, name)


class TestEditOfEdit:
    """R5: A second edit must preserve the first edit's metadata."""

    def test_second_edit_keeps_first_edit_images(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        from server.apps.reviews.schemas import ReviewEditIn, ReviewSubmitIn

        user = _user("edit2@example.com")
        out = services.submit_review(
            user,
            hut,
            ReviewSubmitIn.model_validate({"rating": 10, "opinion": "initial"}),
            "de",
        )
        sig = out.signature
        # First edit: add an image.
        services.edit_review(
            user,
            hut,
            sig,
            ReviewEditIn.model_validate(
                {
                    "rating": 50,
                    "images": [{"src": "https://files.mangrove.reviews/a.jpg"}],
                }
            ),
        )
        # Second edit: change only the rating (no images in DTO).
        result = services.edit_review(
            user,
            hut,
            sig,
            ReviewEditIn.model_validate({"rating": 90}),
        )
        # The image from the FIRST edit must survive.
        assert result.images
        assert result.images[0].src == "https://files.mangrove.reviews/a.jpg"
        assert result.rating == 90

    def test_rating_omitted_is_preserved(self, hut: Any, use_fake_client: Any) -> None:
        from server.apps.reviews.schemas import ReviewEditIn, ReviewSubmitIn

        user = _user("edit3@example.com")
        out = services.submit_review(
            user,
            hut,
            ReviewSubmitIn.model_validate({"rating": 75, "opinion": "good"}),
            "de",
        )
        # Edit: change only the opinion (rating is None in DTO).
        result = services.edit_review(
            user,
            hut,
            out.signature,
            ReviewEditIn.model_validate({"opinion": "updated opinion"}),
        )
        # The rating from the original must be carried forward.
        assert result.rating == 75
        assert result.opinion == "updated opinion"


class TestReplyEditDelete:
    """R7: Replies can be edited and deleted via the extended gate."""

    def test_reply_edit_and_delete(self, hut: Any, use_fake_client: Any) -> None:

        client, user = _user_and_client("reply-edit@example.com")
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="parent-r", subject=subject)]

        # Post a reply.
        created = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-r/reply",
            {"opinion": "original reply"},
            content_type="application/json",
        )
        assert created.status_code == 201, created.content
        reply_sig = created.json()["signature"]

        # Edit the reply (the gate must accept reply targets).
        edited = client.post(
            f"/v1/huts/{hut.slug}/reviews/{reply_sig}/edit",
            {"opinion": "edited reply"},
            content_type="application/json",
        )
        assert edited.status_code == 200, edited.content
        assert edited.json()["opinion"] == "edited reply"

        # Delete the reply.
        deleted = client.post(f"/v1/huts/{hut.slug}/reviews/{reply_sig}/delete")
        assert deleted.status_code == 204, deleted.content


class TestProfile:
    """R19: Reviewer profile get/update."""

    def test_get_and_patch_profile(self) -> None:
        client, _user = _user_and_client("profile@example.com")
        # Get (creates implicitly with minted nickname).
        get_resp = client.get("/v1/my/reviews/profile")
        assert get_resp.status_code == 200
        assert get_resp.json()["nickname"]  # non-empty minted name
        # Patch.
        patch_resp = client.patch(
            "/v1/my/reviews/profile",
            {"nickname": "Alpinist", "language": "fr"},
            content_type="application/json",
        )
        assert patch_resp.status_code == 200, patch_resp.content
        assert patch_resp.json()["nickname"] == "Alpinist"
        assert patch_resp.json()["language"] == "fr"


def _user_and_client(email: str) -> tuple[Client, User]:
    from django.test import Client

    user = _user(email)
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client, user
