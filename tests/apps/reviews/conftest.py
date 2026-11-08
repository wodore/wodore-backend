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
    caches["shared"].clear()
    caches["persistent"].clear()  # image-provider caches (MangroveProvider)
    yield


def _ensure_category_tree() -> None:
    """The amenity→accommodation tree ``HutFactory`` needs (idempotent).

    On a truly fresh test DB the seed loader's categories land root-level
    (its accommodation fallback); CI avoids this via cached pgdata. Tests
    that use ``HutFactory`` must ensure the tree themselves.
    """
    from server.apps.categories.models import Category

    amenity, _created = Category.objects.get_or_create(
        slug="amenity", defaults={"name": "Amenity", "is_active": True}
    )
    Category.objects.get_or_create(
        slug="accommodation",
        parent=amenity,
        defaults={"name": "Accommodation", "is_active": True},
    )


@pytest.fixture
def hut(seed_data: object):
    """A public active hut with OSM and refuges.info sources (stand-ins)."""
    from server.apps.huts.models import HutSource
    from server.apps.organizations.models import Organization

    _ensure_category_tree()
    made = HutFactory()
    org_osm, _created = Organization.objects.get_or_create(
        slug="osm", defaults={"name": "OpenStreetMap"}
    )
    HutSource.objects.create(
        hut=made,
        organization=org_osm,
        source_id="123456",
        name="OSM Hut Name",
        is_current=True,
        source_data={"osm_type": "way", "center_lat": 46.5, "center_lon": 8.0},
    )
    org_refuges, _created = Organization.objects.get_or_create(
        slug="refuges", defaults={"name": "refuges.info"}
    )
    HutSource.objects.create(
        hut=made,
        organization=org_refuges,
        source_id="3760",
        name="OSM Hut Name",
        is_current=True,
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

    def list_reviews(self, subject: str) -> ReviewsResponse:
        # Subject-aware: exact payload.sub matches win (the replies
        # endpoint queries urn:maresi subjects, answered from kid_items);
        # fall back to all items for the plain geo-listing tests.
        pool = self.items + [k for k in self.kid_items if k not in self.items]
        matching = [item for item in pool if item.payload.sub == subject]
        return ReviewsResponse(reviews=list(matching if matching else self.items))

    def list_reviews_by_kid(self, _kid_pem: str) -> ReviewsResponse:
        return ReviewsResponse(reviews=list(self.kid_items))

    def review(self, signature: str) -> ReviewItem | None:
        for item in self.items:
            if item.signature == signature:
                return item
        return None

    def upload_photos(self, files: "list[tuple[str, bytes, str]]") -> "list[str]":
        return [f"fakehash{i}" for i in range(len(files))]

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


class FakeRefugesClient:
    """In-memory stand-in for the refuges.info provider."""

    def __init__(
        self, comments: "list[t.Any] | None" = None, fail: bool = False
    ) -> None:
        self.comments = comments or []
        self.fail = fail
        self.calls: list[str] = []

    def list_comments(self, point_id: str) -> "list[t.Any]":
        self.calls.append(point_id)
        if self.fail:
            raise RuntimeError("provider down")
        return list(self.comments)


@pytest.fixture(autouse=True)
def _stub_refuges_provider(monkeypatch: pytest.MonkeyPatch) -> FakeRefugesClient:
    """Never hit the live refuges.info API from tests (default: empty).

    The ``hut`` fixture carries a refuges.info HutSource; without this
    autouse stub every listing test would hit the LIVE provider (slow,
    real comments). Tests wanting provider data set ``fake_refuges.comments``.
    """
    from server.apps.reviews import refuges_info

    fake = FakeRefugesClient()
    monkeypatch.setattr(refuges_info, "_client", fake)
    return fake


@pytest.fixture
def fake_refuges(_stub_refuges_provider: FakeRefugesClient) -> FakeRefugesClient:
    """The autouse provider stub, requestable when a test sets comments."""
    return _stub_refuges_provider


@pytest.fixture(autouse=True)
def _stub_mangrove_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Never hit the live Mangrove API from tests — AUTOUSE.

    Opus review B5: a listing test without an explicit fake reached
    api.mangrove.reviews with the test hut's subject.
    """
    from server.apps.reviews import services

    fake = FakeClient()
    monkeypatch.setattr(services, "_client", fake)
    return fake


@pytest.fixture
def use_fake_client(_stub_mangrove_client: FakeClient) -> FakeClient:
    """The autouse Mangrove stub, requestable when a test sets items."""
    return _stub_mangrove_client


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
