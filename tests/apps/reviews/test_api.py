"""API contract tests through the real /v1 router (specs: hut-reviews)."""

import typing as t
from typing import Any

import pytest

from django.test import Client

from server.apps.accounts.models import User
from server.apps.reviews.models import SubmittedReview
from server.apps.reviews.services import subject_for_hut

from .conftest import log_row, review_item

pytestmark = pytest.mark.django_db


def _user(email: str = "hiker@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


def _logged_in_client() -> tuple[Client, User]:
    user = _user()
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client, user


def _password_token(username: str, password: str) -> str:
    """A bearer token from the built-in dev provider (password grant)."""
    response = Client().post(
        "/oauth/local/token/",
        data={
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": "wodore-local-dev-password",
            "client_secret": "wodore-local-dev-secret",
        },
    )
    assert response.status_code == 200, response.content
    return str(response.json()["access_token"])


@pytest.fixture(scope="module")
def local_users(django_db_setup: None, django_db_blocker: Any) -> t.Iterator[None]:
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("local_auth_users")
    yield


class TestReadEndpoints:
    def test_anonymous_list_with_envelope(self, hut: Any, use_fake_client: Any) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="s1", subject=subject)]
        response = Client().get(f"/v1/huts/{hut.slug}/reviews")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["license"] == "CC-BY-4.0"
        assert body["attribution"] == "https://mangrove.reviews"
        assert body["data"][0]["signature"] == "s1"
        assert "public" in response.headers.get("Cache-Control", "")

    def test_unknown_hut_404_with_problem_members(self, hut: Any) -> None:
        response = Client().get("/v1/huts/does-not-exist/reviews")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "not_found"
        assert body["title"] and body["status"] == 404  # RFC 9457 members

    def test_inactive_hut_404(self, hut: Any) -> None:
        from server.apps.huts.models import Hut

        Hut.objects.filter(pk=hut.pk).update(is_active=False)
        response = Client().get(f"/v1/huts/{hut.slug}/reviews")
        assert response.status_code == 404

    def test_summary_endpoint(self, hut: Any, use_fake_client: Any) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature="a", subject=subject, rating=80),
            review_item(signature="b", subject=subject, rating=None, opinion="t"),
        ]
        response = Client().get(f"/v1/huts/{hut.slug}/reviews/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["rating_count"] == 1
        assert body["positive_count"] == 1

    def test_batch_summary_bounded(self) -> None:
        slugs = ",".join(f"slug{i}" for i in range(51))
        response = Client().get(f"/v1/reviews/summary?slugs={slugs}")
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    @pytest.mark.usefixtures("use_fake_client")
    def test_batch_summary_zeroed_for_unknown(self, hut: Any) -> None:
        response = Client().get(f"/v1/reviews/summary?slugs=nosuchhut,{hut.slug}")
        assert response.status_code == 200
        by_slug = {row["slug"]: row for row in response.json()["data"]}
        assert by_slug["nosuchhut"]["count"] == 0
        assert by_slug[hut.slug]["count"] == 0

    def test_upstream_failure_maps_to_503(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services

        fake_client.fail_submit = False
        monkeypatch.setattr(services, "_client", _UnavailableClient(fake_client))
        response = Client().get(f"/v1/huts/{hut.slug}/reviews")
        assert response.status_code == 503
        assert response.json()["code"] == "service_unavailable"

    @pytest.mark.usefixtures("use_fake_client")
    def test_reads_disabled_serve_empty(self, hut: Any) -> None:
        from django.test import override_settings

        with override_settings(MANGROVE_ENABLED=False):
            response = Client().get(f"/v1/huts/{hut.slug}/reviews")
            assert response.status_code == 200
            assert response.json()["count"] == 0


class _UnavailableClient:
    """Adapter whose list call always fails as unavailable."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def list_reviews(self, _subject: str) -> Any:
        from server.apps.reviews.client import UpstreamUnavailable

        raise UpstreamUnavailable("down")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class TestWriteEndpoints:
    @pytest.mark.usefixtures("use_fake_client")
    def test_anonymous_submit_401(self, hut: Any) -> None:
        response = Client().post(
            f"/v1/huts/{hut.slug}/reviews/submit",
            {"rating": 75},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"

    @pytest.mark.usefixtures("use_fake_client")
    def test_submit_201_with_derived_signature(self, hut: Any) -> None:
        client, user = _logged_in_client()
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/submit",
            {"rating": 75, "opinion": "great hut"},
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["signature"]
        assert body["rating"] == 75
        row = SubmittedReview.objects.get(signature=body["signature"])
        assert row.user == user
        assert row.state == SubmittedReview.State.accepted
        assert "no-store" in response.headers.get("Cache-Control", "")

    @pytest.mark.usefixtures("use_fake_client", "local_users")
    def test_submit_via_bearer_token(self, hut: Any) -> None:
        token = _password_token("admin@local.test", "admin-dev")
        response = Client().post(
            f"/v1/huts/{hut.slug}/reviews/submit",
            {"rating": 50},
            content_type="application/json",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201, response.content
        assert SubmittedReview.objects.filter(hut_slug=hut.slug).exists()

    @pytest.mark.usefixtures("use_fake_client")
    def test_submit_validation_errors(self, hut: Any) -> None:
        client, _user = _logged_in_client()
        for payload in (
            {"rating": 120},  # out of range
            {"nickname": "x"},  # neither rating nor opinion
            {"rating": 50, "unknown_key": 1},  # extra key forbidden
            {"rating": 50, "is_affiliated": False},  # flags only when true
            {"rating": 50, "images": [{"src": "http://insecure.example/x.png"}]},
        ):
            response = client.post(
                f"/v1/huts/{hut.slug}/reviews/submit",
                payload,
                content_type="application/json",
            )
            assert response.status_code == 400, payload
            assert response.json()["code"] == "validation_error", payload

    @pytest.mark.usefixtures("use_fake_client")
    def test_quota_429_with_retry_after(self, hut: Any) -> None:
        from django.test import override_settings

        client, user = _logged_in_client()
        with override_settings(MANGROVE_QUOTA_SUBMIT=1):
            first = client.post(
                f"/v1/huts/{hut.slug}/reviews/submit",
                {"rating": 10},
                content_type="application/json",
            )
            assert first.status_code == 201
            second = client.post(
                f"/v1/huts/{hut.slug}/reviews/submit",
                {"rating": 20},
                content_type="application/json",
            )
            assert second.status_code == 429
            body = second.json()
            assert body["code"] == "review_quota_exceeded"
            assert "Resets" in body["detail"]
            assert second.headers.get("Retry-After")

    @pytest.mark.usefixtures("use_fake_client")
    def test_edit_delete_own_review(self, hut: Any) -> None:
        client, user = _logged_in_client()
        created = client.post(
            f"/v1/huts/{hut.slug}/reviews/submit",
            {"rating": 10},
            content_type="application/json",
        )
        signature = created.json()["signature"]

        edited = client.post(
            f"/v1/huts/{hut.slug}/reviews/{signature}/edit",
            {"rating": 90},
            content_type="application/json",
        )
        assert edited.status_code == 200
        assert edited.json()["rating"] == 90
        # The edit action was relayed and logged as its own row.
        assert SubmittedReview.objects.filter(
            action=SubmittedReview.Action.edit, user=user, target_signature=signature
        ).exists()

        deleted = client.post(f"/v1/huts/{hut.slug}/reviews/{signature}/delete")
        assert deleted.status_code == 204
        assert SubmittedReview.objects.filter(
            action=SubmittedReview.Action.delete, user=user
        ).exists()

    def test_edit_foreign_review_403(self, hut: Any, use_fake_client: Any) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        other = review_item(signature="foreign-sig", subject=subject)
        use_fake_client.items = [other]
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/foreign-sig/edit",
            {"rating": 1},
            content_type="application/json",
        )
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permission"

    @pytest.mark.usefixtures("use_fake_client")
    def test_target_of_other_hut_404(self, hut: Any) -> None:
        client, user = _logged_in_client()
        log_row(user, "otherhut", "geo:0,0?q=otherhut&u=30", "other-sig")
        response = client.post(f"/v1/huts/{hut.slug}/reviews/other-sig/delete")
        assert response.status_code == 404

    def test_report_requires_reason(self, hut: Any, use_fake_client: Any) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="rep-1", subject=subject)]
        missing = client.post(
            f"/v1/huts/{hut.slug}/reviews/rep-1/report",
            {},
            content_type="application/json",
        )
        assert missing.status_code == 400
        ok = client.post(
            f"/v1/huts/{hut.slug}/reviews/rep-1/report",
            {"opinion": "spam"},
            content_type="application/json",
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "reported"

    @pytest.mark.usefixtures("use_fake_client")
    def test_writes_disabled_503(self, hut: Any) -> None:
        from django.test import override_settings

        client, _user = _logged_in_client()
        with override_settings(MANGROVE_ENABLED=False):
            response = client.post(
                f"/v1/huts/{hut.slug}/reviews/submit",
                {"rating": 10},
                content_type="application/json",
            )
            assert response.status_code == 503
            assert response.json()["code"] == "service_unavailable"


class TestMyReviews:
    def test_my_reviews_with_hut_annotation(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        client, user = _logged_in_client()
        subject = subject_for_hut(hut)
        # The user's key reviews: one on our hut, one foreign.
        from server.apps.reviews import services

        key, _profile = services.get_or_mint_key(user)
        use_fake_client.kid_items = [
            review_item(signature="own-hut", subject=subject),
            review_item(signature="own-foreign", subject="https://example.com"),
        ]
        response = client.get("/v1/my/reviews")
        assert response.status_code == 200
        rows = {row["signature"]: row for row in response.json()}
        assert rows["own-hut"]["hut_slug"] == hut.slug
        assert rows["own-foreign"]["hut_slug"] is None
        assert "no-store" in response.headers.get("Cache-Control", "")

    def test_my_reviews_anonymous_401(self) -> None:
        response = Client().get("/v1/my/reviews")
        assert response.status_code == 401
