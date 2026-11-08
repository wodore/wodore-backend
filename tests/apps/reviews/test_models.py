"""Model tests: custody, constraints, PROTECT guards, PII-safe defaults."""

import pytest

from django.db import IntegrityError, transaction

from server.apps.accounts.models import User
from server.apps.reviews.models import (
    ReviewBlacklist,
    ReviewerKey,
    ReviewerProfile,
    SubmittedReview,
    decrypt_private_jwk,
    encrypt_private_jwk,
)

pytestmark = pytest.mark.django_db


def _user(email: str = "hiker@example.com") -> User:
    return User.objects.create_user(email=email, password="x")  # type: ignore  # custom manager/queryset inference gap


class TestReviewerKey:
    def test_one_key_per_user(self) -> None:
        user = _user()
        ReviewerKey.objects.create(user=user, kid="k1", private_jwk_encrypted="e1")
        with pytest.raises(IntegrityError), transaction.atomic():
            ReviewerKey.objects.create(user=user, kid="k2", private_jwk_encrypted="e2")

    def test_encryption_roundtrip(self) -> None:
        secret = '{"kty": "EC", "d": "very-secret"}'
        token = encrypt_private_jwk(secret)
        assert token != secret
        assert "very-secret" not in token
        assert decrypt_private_jwk(token) == secret

    def test_user_deletion_is_protected(self) -> None:
        user = _user()
        ReviewerKey.objects.create(user=user, kid="k1", private_jwk_encrypted="e1")
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            user.delete()

    def test_log_row_protects_user_too(self) -> None:
        from django.db.models import ProtectedError

        user = _user()
        from django.utils import timezone

        SubmittedReview.objects.create(
            user=user,
            hut_slug="x",
            subject="geo:0,0?q=x&u=30",
            signature="sig",
            iat=timezone.now(),
            jwt="a.b.c",
        )
        with pytest.raises(ProtectedError):
            user.delete()


class TestReviewerProfile:
    def test_nickname_is_minted_and_non_identifying(self) -> None:
        user = _user("someone@example.com")
        profile = ReviewerProfile.objects.create(user=user)
        assert profile.nickname
        assert "example" not in profile.nickname
        assert "someone" not in profile.nickname


class TestSubmittedReview:
    def test_signature_unique(self) -> None:
        from django.utils import timezone

        user = _user()
        common = dict(
            user=user,
            hut_slug="x",
            subject="geo:0,0?q=x&u=30",
            iat=timezone.now(),
            jwt="a.b.c",
        )
        SubmittedReview.objects.create(signature="dup", **common)
        with pytest.raises(IntegrityError), transaction.atomic():
            SubmittedReview.objects.create(signature="dup", **common)

    def test_invalid_action_rejected(self) -> None:
        from django.utils import timezone

        user = _user()
        with pytest.raises(IntegrityError), transaction.atomic():
            SubmittedReview.objects.create(
                user=user,
                hut_slug="x",
                subject="geo:0,0?q=x&u=30",
                signature="s2",
                iat=timezone.now(),
                jwt="a.b.c",
                action="nonsense",
            )


class TestReviewBlacklist:
    def test_signature_unique(self) -> None:
        ReviewBlacklist.objects.create(signature="abc")
        ReviewBlacklist.objects.get_or_create(signature="abc")
        assert ReviewBlacklist.objects.count() == 1
