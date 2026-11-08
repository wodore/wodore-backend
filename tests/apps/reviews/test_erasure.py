"""Erasure command tests (spec: review-identity, Erasure path)."""

import typing as t
from typing import Any

import pytest

from django.core.management import call_command

from server.apps.accounts.models import User
from server.apps.reviews import services
from server.apps.reviews.client import subject_for_hut
from server.apps.reviews.models import ReviewerKey, ReviewerProfile, SubmittedReview

from .conftest import log_row

pytestmark = pytest.mark.django_db


def _user(email: str = "gone@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


def _erased_user(hut: Any, reviews: int = 2) -> tuple[User, list[str]]:
    user = _user()
    subject = subject_for_hut(hut)
    services.get_or_mint_key(user)
    signatures = [f"erase-sig-{i}" for i in range(reviews)]
    for signature in signatures:
        log_row(user, hut.slug, subject, signature)
    return user, signatures


class TestErasure:
    def test_full_erasure_destroys_everything(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        user, signatures = _erased_user(hut)
        call_command("reviews_erase_user", user.email)
        assert not SubmittedReview.objects.filter(user=user).exists()
        assert not ReviewerKey.objects.filter(user=user).exists()
        assert not ReviewerProfile.objects.filter(user=user).exists()
        # Delete actions were relayed (one per accepted review).
        assert len(use_fake_client.submitted) == len(signatures)

    def test_other_users_untouched(self, hut: Any, use_fake_client: Any) -> None:
        gone, _sigs = _erased_user(hut)
        keeper = _user("keeper@example.com")
        log_row(keeper, hut.slug, subject_for_hut(hut), "keeper-sig")
        call_command("reviews_erase_user", gone.email)
        assert SubmittedReview.objects.filter(user=keeper).exists()
        assert ReviewerKey.objects.filter(user=keeper).exists() is False  # never minted

    def test_upstream_refusal_is_idempotent_success(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services as services_module

        fake_client.reject_submit = True
        monkeypatch.setattr(services_module, "_client", fake_client)
        user, _sigs = _erased_user(hut)
        call_command("reviews_erase_user", user.email)  # must not raise
        assert not SubmittedReview.objects.filter(user=user).exists()

    def test_upstream_unavailable_keeps_rows(
        self, hut: Any, fake_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services as services_module

        fake_client.fail_submit = True
        monkeypatch.setattr(services_module, "_client", fake_client)
        user, _sigs = _erased_user(hut)
        with pytest.raises(SystemExit):
            call_command("reviews_erase_user", user.email)
        # Nothing destroyed — the command is resumable.
        assert SubmittedReview.objects.filter(user=user).exists()
        assert ReviewerKey.objects.filter(user=user).exists()

    def test_export_mode_dumps_log_first(
        self, hut: Any, use_fake_client: Any, tmp_path: Any
    ) -> None:
        user, _sigs = _erased_user(hut, reviews=1)
        export = tmp_path / "log.jsonl"
        call_command("reviews_erase_user", user.email, export=str(export))
        content = export.read_text()
        assert "erase-sig-0" in content
        assert '"jwt"' in content  # verbatim JWTs — independently verifiable

    def test_user_deletion_works_after_erasure(
        self, hut: Any, use_fake_client: Any
    ) -> None:
        user, _sigs = _erased_user(hut)
        call_command("reviews_erase_user", user.email)
        user.delete()  # PROTECT no longer blocks: nothing references it
        assert not User.objects.filter(email=user.email).exists()


def _unused(_t: t.Any) -> None:  # pragma: no cover - keeps typing import used
    return None
