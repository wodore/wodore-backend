"""Service-layer tests: quota, filters, aggregates, write relay, ownership."""

import typing as t
from typing import Any

import pytest

from server.apps.accounts.models import User
from server.apps.reviews import services
from server.apps.reviews.models import SubmittedReview
from server.apps.reviews.schemas import ReviewSubmitIn
from server.apps.reviews.services import subject_for_hut

from .conftest import blacklist, log_row, review_item

pytestmark = pytest.mark.django_db


def _user(email: str = "hiker@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


def _dto(**kwargs: Any) -> ReviewSubmitIn:
    base: dict[str, Any] = {"rating": 75}
    base.update(kwargs)
    return ReviewSubmitIn.model_validate(base)


class TestOsmId:
    def test_linked_hut_stamps_osm_id(self, hut: Any) -> None:
        assert services.osm_id_for_hut(hut) == "way/123456"

    def test_unlinked_hut_gets_none(self, hut: Any) -> None:
        from server.apps.huts.models import HutSource

        HutSource.objects.filter(hut=hut).update(is_current=False)
        assert services.osm_id_for_hut(hut) is None

    def test_invalid_osm_type_gets_none(self, hut: Any) -> None:
        from server.apps.huts.models import HutSource

        HutSource.objects.filter(hut=hut).update(
            source_data={"osm_type": "blob"}, is_current=True
        )
        assert services.osm_id_for_hut(hut) is None


class TestQuota:
    def test_submission_quota_enforced_with_retry_after(self, hut: Any) -> None:
        from dmr import APIError

        from django.test import override_settings

        user = _user()
        subject = subject_for_hut(hut)
        with override_settings(MANGROVE_QUOTA_SUBMIT=2):
            for _ in range(2):
                log_row(user, hut.slug, subject, f"sig-{_}")
            with pytest.raises(APIError) as excinfo:
                services.enforce_quota(user, "submit")
            assert excinfo.value.status_code == 429
            headers: dict[str, str] = dict(excinfo.value.headers or {})
            assert "Retry-After" in headers

    def test_edit_class_counted_separately(self, hut: Any) -> None:
        user = _user()
        subject = subject_for_hut(hut)
        log_row(user, hut.slug, subject, "sig-e1", action=SubmittedReview.Action.edit)
        services.enforce_quota(user, "submit")  # submissions unaffected

    def test_pending_and_failed_attempts_count(self, hut: Any) -> None:
        user = _user()
        subject = subject_for_hut(hut)
        log_row(user, hut.slug, subject, "s-failed", state=SubmittedReview.State.failed)
        # failed attempts consume quota (attempts were relayed)
        with pytest.raises(Exception):  # noqa: B017 - exact type below
            from django.test import override_settings

            with override_settings(MANGROVE_QUOTA_SUBMIT=1):
                log_row(user, hut.slug, subject, "s-ok")
                services.enforce_quota(user, "submit")


class TestReads:
    def test_list_filters_blacklist_and_foreign_subjects(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature="mine-1", subject=subject, rating=25, iat=1),
            review_item(signature="mine-2", subject=subject, rating=50, iat=2),
            review_item(
                signature="mine-3", subject=subject, rating=100, opinion="t", iat=3
            ),
            review_item(signature="foreign", subject="geo:0,0?q=other&u=100"),
        ]
        blacklist("mine-2")
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert [r.signature for r in envelope.data] == ["mine-3", "mine-1"]
        assert envelope.count == 2
        assert envelope.license == "CC-BY-4.0"

    def test_local_pagination(self, hut: Any, use_fake_client: Any) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature=f"s{i}", subject=subject, iat=1_790_000_000 + i)
            for i in range(5)
        ]
        page = services.list_reviews(hut, limit=2, offset=1)
        assert [r.signature for r in page.data] == ["s3", "s2"]
        assert page.count == 5

    def test_summary_math_over_rated_only(self, hut: Any, use_fake_client: Any) -> None:
        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(signature="a", subject=subject, rating=25),
            review_item(signature="b", subject=subject, rating=50),
            review_item(signature="c", subject=subject, rating=100),
            review_item(signature="d", subject=subject, rating=None, opinion="only"),
        ]
        summary = services.summary_for_hut(hut)
        assert summary.count == 4
        assert summary.rating_count == 3
        assert summary.rating_mean == 58.3
        assert summary.positive_count == 1
        assert summary.opinion_count == 1

    def test_image_allowlist_at_serving(self, hut: Any, use_fake_client: Any) -> None:
        from server.apps.reviews.client import ReviewImagePayload

        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(
                signature="img",
                subject=subject,
                images=[
                    ReviewImagePayload(src="https://files.mangrove.reviews/a.png"),
                    ReviewImagePayload(src="https://evil.example/b.png"),
                    ReviewImagePayload(src="http://files.mangrove.reviews/c.png"),
                ],
            )
        ]
        envelope = services.list_reviews(hut, limit=10, offset=0)
        assert [i.src for i in envelope.data[0].images] == [
            "https://files.mangrove.reviews/a.png"
        ]

    @pytest.mark.usefixtures("use_fake_client")
    def test_batch_summary_bounded_and_sorted(self, hut: Any) -> None:
        envelope = services.batch_summary(["zeta", "alpha", hut.slug, "alpha"])
        assert [s.slug for s in envelope.data] == sorted({hut.slug, "alpha", "zeta"})
        assert all(s.count == 0 for s in envelope.data)

    def test_reads_disabled_serve_empty(self, hut: Any) -> None:
        from django.test import override_settings

        with override_settings(MANGROVE_ENABLED=False):
            assert services.list_reviews(hut, 20, 0).count == 0


class TestSubmitRelay:
    def test_submit_enriches_and_logs_accepted(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        user = _user()
        out = services.submit_review(
            user,
            hut,
            _dto(rating=75, opinion="nice", is_personal_experience=True),
            "de",
        )
        assert use_fake_client.submitted, "JWT was relayed"
        jwt = use_fake_client.submitted[0]
        payload = _payload(jwt)
        assert payload["sub"] == subject_for_hut(hut)
        assert payload["rating"] == 75
        assert payload["metadata"]["client_id"] == "https://wodore.com"
        assert payload["metadata"]["license"] == "CC-BY-4.0"
        assert payload["metadata"]["osm_id"] == "way/123456"
        assert payload["metadata"]["language"] == "de"
        assert payload["metadata"]["is_personal_experience"] is True
        assert "is_affiliated" not in payload["metadata"]
        row = SubmittedReview.objects.get(signature=out.signature)
        assert row.state == SubmittedReview.State.accepted
        assert row.user == user

    @pytest.mark.usefixtures("use_fake_client")
    def test_write_through_cache_merge(self, hut: Any) -> None:
        """The author's own review is visible immediately after submit.

        Even when the upstream listing does not (yet) include it — the
        cache entry is merged, not invalidated (design D6).
        """
        from django.core.cache import caches

        from server.apps.reviews.services import _list_cache_key

        shared = caches["shared"]
        subject = subject_for_hut(hut)
        shared.set(_list_cache_key(subject), [], 60)  # pre-existing entry
        user = _user()
        out = services.submit_review(user, hut, _dto(rating=50), "de")
        cached = shared.get(_list_cache_key(subject))
        assert cached is not None, "cache entry must survive (merged, not dropped)"
        assert any(item["signature"] == out.signature for item in cached)
        # And the served list reflects it without any upstream change:
        envelope = services.list_reviews(hut, limit=20, offset=0)
        assert any(review.signature == out.signature for review in envelope.data)

    def test_submit_failure_marks_failed_and_raises(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dmr import APIError

        fake_client.fail_submit = True
        monkeypatch.setattr(services, "_client", fake_client)
        user = _user()
        with pytest.raises(APIError) as excinfo:
            services.submit_review(user, hut, _dto(rating=50), "de")
        assert excinfo.value.status_code == 503
        row = SubmittedReview.objects.get(user=user)
        assert row.state == SubmittedReview.State.failed

    def test_delete_is_idempotent_on_refusal(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = _user()
        services.get_or_mint_key(user)  # delete requires an existing key (N4)
        subject = subject_for_hut(hut)
        log_row(user, hut.slug, subject, "target-sig")
        fake_client.reject_submit = True
        monkeypatch.setattr(services, "_client", fake_client)
        services.delete_review(user, hut, "target-sig")
        rows = SubmittedReview.objects.filter(action=SubmittedReview.Action.delete)
        assert rows.count() == 1
        delete_row = rows.first()
        assert delete_row is not None
        assert delete_row.state == SubmittedReview.State.accepted


class TestOwnership:
    @pytest.mark.usefixtures("use_fake_client")
    def test_owns_via_log(self, hut: Any) -> None:
        user = _user()
        subject = subject_for_hut(hut)
        log_row(user, hut.slug, subject, "owned-sig")
        key, _profile = services.get_or_mint_key(user)
        assert services.owns_review(user, key, "owned-sig")

    def test_foreign_review_refused(self, hut: Any, use_fake_client: Any) -> None:
        user = _user()
        subject = subject_for_hut(hut)
        foreign = review_item(signature="foreign-sig", subject=subject)
        use_fake_client.items = [foreign]
        key, _profile = services.get_or_mint_key(user)
        assert not services.owns_review(user, key, "foreign-sig")

    @pytest.mark.usefixtures("use_fake_client")
    def test_target_must_belong_to_hut(self, hut: Any) -> None:
        """The 404 gate checks the hut's visible list (own overlay incl.)."""
        from dmr import APIError

        user = _user()
        subject = subject_for_hut(hut)
        log_row(user, hut.slug, subject, "own-sig")
        log_row(user, "otherhut", "geo:0,0?q=otherhut&u=30", "other-sig")
        # Own review: visible via the own-write overlay → gate passes.
        services._refuse_foreign_target(hut, "own-sig")
        # Foreign-hut target: not in this hut's visible list → 404.
        with pytest.raises(APIError) as excinfo:
            services._refuse_foreign_target(hut, "other-sig")
        assert excinfo.value.status_code == 404
        # Provider ids are never actionable.
        with pytest.raises(APIError):
            services._refuse_foreign_target(hut, "refuges-info:123")


def _payload(jwt: str) -> dict[str, t.Any]:
    import base64
    import json

    part = jwt.split(".")[1]
    return t.cast(
        dict[str, t.Any],
        json.loads(base64.urlsafe_b64decode(part + "=" * ((4 - len(part) % 4) % 4))),
    )
