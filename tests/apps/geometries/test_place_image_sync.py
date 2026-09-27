"""Tests for the place-generic background refresh (spec: external-image-pinning §5).

Covers sync orchestration for huts and geoplaces, the q2 enqueue rules
(24 h TTL, debounce), endpoint wiring, dead-origin flagging, and the
geoimages_pin command.
"""

from datetime import timedelta

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries import pinning
from server.apps.geometries.pinning import (
    PIN_REFRESH_TTL_S,
    maybe_enqueue_place_refresh,
    pin_place_images,
    sync_place_images,
    sync_place_images_task,
)
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image

from .test_image_pinning import _result

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch):
    """Private locmem caches: response cache and the refresh-debounce lock."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    name = f"test-{uuid4().hex}"
    cache = LocMemCache(name, {})
    monkeypatch.setattr(irc, "_cache", lambda: cache)
    monkeypatch.setattr(pinning, "_pin_cache", lambda: LocMemCache(name, {}))


class _FetchStub:
    """Async stand-in for fetch_images_for_place inside pinning.sync_*."""

    def __init__(self, results):
        self.results = results
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        return self.results, {"location": {"lat": 46.5, "lon": 7.5}}


@pytest.fixture
def hut(seed_data):
    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    hut.images_pinned_at = None
    hut.save(update_fields=["images_pinned_at"])
    return hut


class TestSyncPlaceImages:
    def test_sync_pins_hut(self, hut, monkeypatch):
        stub = _FetchStub(
            [_result(score=80), _result(source_id="File:B.jpg", score=40)]
        )
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        stats = sync_place_images(hut)
        assert stats.created == 2
        assert HutImageAssociation.objects.filter(hut=hut).count() == 2
        hut.refresh_from_db()
        assert hut.images_pinned_at is not None

    def test_sync_pins_geoplace(self, seed_data, monkeypatch):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        stub = _FetchStub([_result(score=70)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        stats = sync_place_images(place)
        assert stats.created == 1
        assert place.image_associations.count() == 1

    def test_task_unknown_slug_is_logged_not_raised(self):
        sync_place_images_task("hut", "does-not-exist")  # must not raise

    def test_task_syncs_hut(self, hut, monkeypatch):
        stub = _FetchStub([_result(score=60)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        sync_place_images_task("hut", hut.slug)
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1


class TestMaybeEnqueue:
    def _spy(self, monkeypatch):
        calls = []

        def _fake_async_task(func, *args, **kwargs):
            calls.append((func, args))

        monkeypatch.setattr("django_q.tasks.async_task", _fake_async_task)
        return calls

    def test_never_pinned_enqueues_nothing(self, hut, monkeypatch):
        calls = self._spy(monkeypatch)
        assert maybe_enqueue_place_refresh(hut) is False
        assert calls == []

    def test_fresh_pins_enqueue_nothing(self, hut, monkeypatch):
        calls = self._spy(monkeypatch)
        hut.images_pinned_at = timezone.now()
        hut.save(update_fields=["images_pinned_at"])
        assert maybe_enqueue_place_refresh(hut) is False
        assert calls == []

    def test_stale_pins_enqueue_once_then_debounce(self, hut, monkeypatch):
        calls = self._spy(monkeypatch)
        hut.images_pinned_at = timezone.now() - timedelta(
            seconds=PIN_REFRESH_TTL_S + 3600
        )
        hut.save(update_fields=["images_pinned_at"])
        assert maybe_enqueue_place_refresh(hut) is True
        assert maybe_enqueue_place_refresh(hut) is False  # debounced
        assert len(calls) == 1
        assert calls[0][0] == "server.apps.geometries.pinning.sync_place_images_task"
        assert calls[0][1] == ("hut", hut.slug)


class TestEndpointEnqueue:
    def test_stale_hut_fast_path_enqueues(self, hut, monkeypatch):
        from ninja.testing import TestClient

        from server.apps.geometries.api_images import router

        calls = []

        def _fake_async_task(func, *args, **kwargs):
            calls.append(args)

        monkeypatch.setattr("django_q.tasks.async_task", _fake_async_task)
        pin_place_images(hut, [_result(score=80)])
        hut.images_pinned_at = timezone.now() - timedelta(days=2)
        hut.save(update_fields=["images_pinned_at"])

        client = TestClient(router)
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        assert calls == [("hut", hut.slug)]
        # Second hit within the debounce window: no new task.
        client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=11")
        assert len(calls) == 1


class TestDeadOriginFlagging:
    def test_dead_origin_moves_to_review(self, hut, monkeypatch):
        pin_place_images(
            hut,
            [
                _result(score=80),
                _result(
                    source_id="File:Dead.jpg",
                    url="https://upload.wikimedia.org/x/Dead_1920.jpg",
                    score=70,
                ),
            ],
        )
        # Fresh results only contain File:Test.jpg; File:Dead.jpg origin 404s.
        stub = _FetchStub([_result(score=80)])

        def _head(url, **kwargs):
            class _Resp:
                status_code = 404 if "Dead" in url else 200

            return _Resp()

        monkeypatch.setattr("requests.head", _head)
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        sync_place_images(hut, check_origins=True)

        dead = Image.objects.get(source_ident="wikicommons:File:Dead.jpg")
        assert dead.review_status == Image.ReviewStatusChoices.pending
        assert "Origin gone" in dead.review_comment
        alive = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert alive.review_status == Image.ReviewStatusChoices.approved

    def test_live_origin_untouched(self, hut, monkeypatch):
        pin_place_images(hut, [_result(source_id="File:Alive.jpg", score=70)])
        stub = _FetchStub([])  # missing from results, but origin is alive

        def _head(url, **kwargs):
            class _Resp:
                status_code = 200

            return _Resp()

        monkeypatch.setattr("requests.head", _head)
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        sync_place_images(hut, check_origins=True)
        image = Image.objects.get(source_ident="wikicommons:File:Alive.jpg")
        assert image.review_status == Image.ReviewStatusChoices.approved
        assert HutImageAssociation.objects.filter(hut=hut).exists()  # not deleted


class TestGeoimagesPinCommand:
    def test_dry_run_reports(self, hut, capsys):
        call_command("geoimages_pin", place=hut.slug, dry_run=True)
        out = capsys.readouterr().out
        assert "would sync hut" in out and hut.slug in out

    def test_single_place_sync(self, hut, monkeypatch):
        stub = _FetchStub([_result(score=55)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        call_command("geoimages_pin", place=hut.slug)
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1

    def test_unknown_place_raises(self):
        with pytest.raises(CommandError):
            call_command("geoimages_pin", place="nope")

    def test_requires_scope(self):
        with pytest.raises(CommandError):
            call_command("geoimages_pin")

    def test_all_sweep_covers_huts_and_pinned_geoplaces(
        self, hut, seed_data, monkeypatch
    ):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        pin_place_images(place, [_result(score=10)])  # geoplace now has pins

        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs):
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )
        call_command("geoimages_pin", all=True)
        assert hut.slug in seen and place.slug in seen


class TestImagorWarmup:
    """--warmup-image-cache: metadata-only sync stays, pixels prefetched."""

    def _settings(self, settings):
        settings.IMAGOR_URL = "http://imagor.test"
        settings.IMAGOR_KEY = ""

    def test_warms_preview_and_medium(self, hut, monkeypatch, settings):
        from unittest.mock import MagicMock

        from server.apps.geometries.pinning import warmup_place_image_cache

        self._settings(settings)
        pin_place_images(
            hut, [_result(score=80), _result(source_id="File:B.jpg", score=40)]
        )

        fetched = []
        fake = MagicMock()
        fake.status_code = 200

        def _get(url, **kwargs):
            fetched.append(url)
            return fake

        monkeypatch.setattr("requests.get", _get)
        warmed = warmup_place_image_cache(hut)
        assert warmed == 4  # 2 pins x (preview + medium)
        assert all(url.startswith("http://imagor.test/") for url in fetched)
        assert len(fetched) == 4

    def test_dead_origin_ignored(self, hut, monkeypatch, settings):
        from unittest.mock import MagicMock

        from server.apps.geometries.pinning import warmup_place_image_cache

        self._settings(settings)
        pin_place_images(hut, [_result(score=80)])

        fake = MagicMock()
        fake.status_code = 404
        monkeypatch.setattr("requests.get", MagicMock(return_value=fake))
        assert warmup_place_image_cache(hut) == 0  # tolerated, not an error

    def test_command_flag_calls_warmup(self, hut, monkeypatch, settings):
        from unittest.mock import MagicMock

        self._settings(settings)
        stub = _FetchStub([_result(score=55)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        warmed = MagicMock(return_value=2)
        monkeypatch.setattr(
            "server.apps.geometries.pinning.warmup_place_image_cache", warmed
        )
        call_command("geoimages_pin", place=hut.slug, warmup_image_cache=True)
        warmed.assert_called_once()
