"""Image gallery provider + reply-image tests (round 3)."""

import asyncio
import typing as t
from typing import Any

import pytest

from django.test import Client

from server.apps.accounts.models import User
from server.apps.reviews import images as images_module
from server.apps.reviews.client import ReviewImagePayload
from server.apps.reviews.services import subject_for_hut

from .conftest import review_item

pytestmark = pytest.mark.django_db


class _Place:
    """Minimal place schema stand-in (slug is all the provider needs)."""

    def __init__(self, slug: str) -> None:
        self.slug = slug


@pytest.mark.django_db(transaction=True)
class TestMangroveProvider:
    # The provider's sync core runs via sync_to_async on another thread:
    # under a plain TestCase that thread cannot see the uncommitted rows
    # (production runs autocommit — this is a test-only artifact).

    def test_review_photos_become_gallery_results(
        self, hut: Any, use_fake_client: Any
    ) -> None:

        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(
                signature="img-r1",
                subject=subject,
                images=[ReviewImagePayload(src="https://files.mangrove.reviews/a.jpg")],
                nickname="fotofranz",
            ),
            review_item(signature="no-img", subject=subject),
        ]
        results = images_module._review_image_results(hut.slug, 10)
        assert len(results) == 1
        result = results[0]
        assert result.provider == "mangrove"
        assert result.source_id == "img-r1:0"
        assert result.url_large == "https://files.mangrove.reviews/a.jpg"
        assert result.license_slug == "cc-by-4.0"
        assert result.author == "fotofranz"
        assert result.captured_at is not None
        assert result.place and result.place["slug"] == hut.slug

    def test_blacklisted_and_foreign_excluded(
        self, hut: Any, use_fake_client: Any
    ) -> None:

        from .conftest import blacklist

        subject = subject_for_hut(hut)
        use_fake_client.items = [
            review_item(
                signature="img-bad",
                subject=subject,
                images=[ReviewImagePayload(src="https://files.mangrove.reviews/b.jpg")],
            ),
            review_item(
                signature="img-foreign",
                subject="geo:0,0?q=other&u=100",
                images=[ReviewImagePayload(src="https://files.mangrove.reviews/c.jpg")],
            ),
        ]
        blacklist("img-bad")
        results = images_module._review_image_results(hut.slug, 10)
        assert results == []

    def test_upstream_failure_degrades_to_empty(
        self, hut: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from server.apps.reviews import services as services_module

        class _BoomClient:
            def list_reviews(self, _subject: str) -> t.Any:
                raise RuntimeError("upstream down")

        monkeypatch.setattr(services_module, "_client", _BoomClient())
        results = images_module._review_image_results(hut.slug, 10)
        assert results == []

    def test_kill_switch_returns_empty(self, hut: Any) -> None:
        from django.test import override_settings

        from server.apps.reviews.images import MangroveProvider

        with override_settings(MANGROVE_ENABLED=False):
            results = asyncio.run(
                MangroveProvider().fetch(
                    [_Place(hut.slug)], lat=46.5, lon=8.0, radius=300, limit=10
                )
            )
        assert results == []

    def test_unknown_slug_skipped(self) -> None:
        from server.apps.reviews.images import MangroveProvider

        results = asyncio.run(
            MangroveProvider().fetch(
                [_Place("no-such-hut")], lat=0.0, lon=0.0, radius=10, limit=10
            )
        )
        assert results == []


class TestReplyImages:
    def test_reply_with_images(self, hut: Any, use_fake_client: Any) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="parent-img", subject=subject)]

        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-img/reply",
            {
                "opinion": "same experience",
                "images": [
                    {"src": "https://files.mangrove.reviews/r.jpg", "label": "r"}
                ],
            },
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["images"][0]["src"] == "https://files.mangrove.reviews/r.jpg"
        # The signed JWT carries the images.
        payload = _payload(use_fake_client.submitted[-1])
        assert payload["images"] == [
            {"src": "https://files.mangrove.reviews/r.jpg", "label": "r"}
        ]

    def test_reply_rejects_http_image(self, hut: Any, use_fake_client: Any) -> None:
        client, _user = _logged_in_client()
        subject = subject_for_hut(hut)
        use_fake_client.items = [review_item(signature="parent-x", subject=subject)]
        response = client.post(
            f"/v1/huts/{hut.slug}/reviews/parent-x/reply",
            {
                "opinion": "x",
                "images": [{"src": "http://insecure.example/r.jpg"}],
            },
            content_type="application/json",
        )
        assert response.status_code == 400


def _logged_in_client() -> tuple[Client, User]:
    user = User.objects.create_user(email="im@y.z", password="x")  # type: ignore  # custom manager/queryset inference gap
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client, user


def _payload(jwt: str) -> dict[str, t.Any]:
    import base64
    import json

    part = jwt.split(".")[1]
    return t.cast(
        dict[str, t.Any],
        json.loads(base64.urlsafe_b64decode(part + "=" * ((4 - len(part) % 4) % 4))),
    )
