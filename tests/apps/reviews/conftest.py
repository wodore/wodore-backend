"""Reviews test fixtures (openspec: reviews-mangrove)."""

import typing as t

import pytest

from tests.factories.huts import HutFactory

from django.core.cache import caches

from server.apps.reviews.client import (
    ReviewImagePayload,
    ReviewItem,
    ReviewPayload,
    ReviewsResponse,
)
from server.apps.reviews.models import ReviewBlacklist, SubmittedReview

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_caches():
    """Local review cache + throttle counters must not leak between tests."""
    caches["default"].clear()
    caches["throttling"].clear()
    yield


@pytest.fixture
def hut():
    """A public active hut with an OSM source (import-pipeline stand-in)."""
    from server.apps.huts.models import HutSource
    from server.apps.organizations.models import Organization

    made = HutFactory()
    org, _created = Organization.objects.get_or_create(
        slug="osm", defaults={"name": "OpenStreetMap"}
    )
    HutSource.objects.create(
        hut=made,
        organization=org,
        source_id="123456",
        is_current=True,
        source_data={"osm_type": "way", "center_lat": 46.5, "center_lon": 8.0},
    )
    return made


class FakeClient:
    """In-memory stand-in for MangroveClient (tests monkeypatch it in)."""

    def __init__(
        self,
        items: list[ReviewItem] | None = None,
        kid_items: list[ReviewItem] | None = None,
        reject_submit: bool = False,
        fail_submit: bool = False,
    ) -> None:
        self.items = items or []
        self.kid_items = kid_items if kid_items is not None else self.items
        self.reject_submit = reject_submit
        self.fail_submit = fail_submit
        self.submitted: list[str] = []

    def list_reviews(self, _subject: str) -> ReviewsResponse:
        return ReviewsResponse(reviews=list(self.items))

    def list_reviews_by_kid(self, _kid_pem: str) -> ReviewsResponse:
        return ReviewsResponse(reviews=list(self.kid_items))

    def review(self, signature: str) -> ReviewItem | None:
        for item in self.items:
            if item.signature == signature:
                return item
        return None

    def submit(self, jwt: str) -> None:
        from server.apps.reviews.client import UpstreamRejected, UpstreamUnavailable

        self.submitted.append(jwt)
        if self.reject_submit:
            raise UpstreamRejected("refused")
        if self.fail_submit:
            raise UpstreamUnavailable("down")


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def use_fake_client(
    fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> FakeClient:
    """Route every service call through the fake upstream."""
    from server.apps.reviews import services

    monkeypatch.setattr(services, "_client", fake_client)
    return fake_client


def review_item(
    *,
    signature: str = "sig0000000000000000000000000000000000000000",
    subject: str = "",
    rating: int | None = 75,
    opinion: str | None = None,
    nickname: str | None = "tester",
    iat: int = 1_791_000_000,
    images: list[ReviewImagePayload] | None = None,
) -> ReviewItem:
    """A well-formed upstream review item on the given subject."""
    metadata: dict[str, t.Any] = {}
    if nickname is not None:
        metadata["nickname"] = nickname
    return ReviewItem(
        jwt="h.p.s",
        kid="-----BEGIN PUBLIC KEY-----fake-----END PUBLIC KEY-----",
        payload=ReviewPayload(
            iat=iat,
            sub=subject,
            rating=rating,
            opinion=opinion,
            images=images,
            metadata=metadata or None,
        ),
        signature=signature,
    )


def log_row(
    user: t.Any, hut_slug: str, subject: str, signature: str, **kwargs: t.Any
) -> SubmittedReview:
    """A submission-log row (accepted review by default)."""
    from django.utils import timezone

    return SubmittedReview.objects.create(
        user=user,
        hut_slug=hut_slug,
        subject=subject,
        action=kwargs.pop("action", SubmittedReview.Action.review),
        state=kwargs.pop("state", SubmittedReview.State.accepted),
        iat=kwargs.pop("iat", timezone.now()),
        signature=signature,
        jwt=kwargs.pop("jwt", "header.payload." + signature),
        **kwargs,
    )


def blacklist(signature: str) -> ReviewBlacklist:
    return ReviewBlacklist.objects.create(signature=signature, reason="test")
