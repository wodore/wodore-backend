"""Tests for the place-generic background refresh (spec: external-image-pinning §5).

Covers sync orchestration for huts and geoplaces, the q2 enqueue rules
(24 h TTL, debounce), endpoint wiring, dead-origin flagging, and the
geoimages_pin command.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from pytest_django.fixtures import SettingsWrapper

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
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
from server.apps.geometries.providers.base import ImageResult
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image

from .test_image_pinning import _result

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch: pytest.MonkeyPatch):
    """Private locmem caches: response cache and the refresh-debounce lock."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    name = f"test-{uuid4().hex}"
    cache = LocMemCache(name, {})
    monkeypatch.setattr(irc, "_cache", lambda: cache)
    monkeypatch.setattr(pinning, "_pin_cache", lambda: LocMemCache(name, {}))


class _FetchStub:
    """Async stand-in for fetch_images_for_place inside pinning.sync_*."""

    def __init__(self, results: list[ImageResult]):
        self.results = results
        self.calls = 0

    async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
        self.calls += 1
        return self.results, {"location": {"lat": 46.5, "lon": 7.5}}


@pytest.fixture
def hut(seed_data: dict[str, int]):
    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    hut.images_pinned_at = None
    hut.save(update_fields=["images_pinned_at"])
    return hut


class TestSyncPlaceImages:
    def test_sync_pins_hut(self, hut: Hut, monkeypatch: pytest.MonkeyPatch):
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

    def test_sync_bridge_keeps_db_connection(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
        """The command pipeline must not release the thread's DB connection.

        ``sync_place_images`` runs while the caller (``geoimages_pin --all``)
        iterates a server-side cursor; the bridge's exit-path cleanup would
        close that connection mid-cursor (staging 2026-10-07)."""
        import server.apps.geometries.providers as providers_mod
        from server.apps.geometries.providers import base as providers_base

        seen = {}
        real_run_async = providers_base.run_async

        def spy_run_async(fn: Callable[..., Any], *args: Any, **kwargs: Any):
            seen["release_db"] = kwargs.get("release_db", True)
            kwargs["release_db"] = False
            return real_run_async(fn, *args, **kwargs)

        monkeypatch.setattr(providers_mod, "run_async", spy_run_async)
        stub = _FetchStub([_result(score=70)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )

        sync_place_images(hut)

        assert stub.calls == 1  # sanity: the pipeline still ran
        assert seen["release_db"] is False


class TestRunAsyncReleaseDb:
    """The bridge's exit-path connection cleanup honours ``release_db``."""

    async def _work(self):
        return "ok"

    def test_default_releases_connections(self, monkeypatch: pytest.MonkeyPatch):
        from server.apps.geometries.providers import base as providers_base

        calls = []
        monkeypatch.setattr(
            providers_base, "_release_thread_db_connections", lambda: calls.append(1)
        )
        assert providers_base.run_async(self._work) == "ok"
        assert calls == [1]

    def test_release_db_false_skips_cleanup(self, monkeypatch: pytest.MonkeyPatch):
        from server.apps.geometries.providers import base as providers_base

        calls = []
        monkeypatch.setattr(
            providers_base, "_release_thread_db_connections", lambda: calls.append(1)
        )
        assert providers_base.run_async(self._work, release_db=False) == "ok"
        assert calls == []

    def test_author_over_column_length_is_trimmed(self, hut: Hut):
        """Provider author strings longer than varchar(255) get trimmed.

        Untrimmed they aborted the whole place's pin run with
        'value too long for type character varying(255)'."""
        result = _result(score=50)
        result.author = "x" * 300
        pin_place_images(hut, [result])
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert len(image.author) == 255

    def test_source_url_over_old_column_length_pins(self, hut: Hut):
        """URLs longer than the old varchar(500) must not abort the run.

        Trimming would break the URL, so the columns were widened to 1000
        (staging: 'value too long for type character varying(500)' on a
        geoplace pin run)."""
        long_url = (
            "https://upload.wikimedia.org/wikipedia/commons/" + "a" * 540 + ".jpg"
        )
        result = _result(score=50, url=long_url)
        pin_place_images(hut, [result])
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.source_url_raw.startswith("https://upload.wikimedia.org/")
        assert len(image.source_url_raw) > 500

    def test_sync_pins_geoplace(
        self, seed_data: dict[str, int], monkeypatch: pytest.MonkeyPatch
    ):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        stub = _FetchStub([_result(score=70)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        stats = sync_place_images(place)
        assert stats.created == 1
        from server.apps.geometries.models import GeoPlaceImageAssociation

        assert GeoPlaceImageAssociation.objects.filter(geo_place=place).count() == 1

    def test_task_unknown_slug_is_logged_not_raised(self):
        sync_place_images_task("hut", "does-not-exist")  # must not raise

    def test_task_syncs_hut(self, hut: Hut, monkeypatch: pytest.MonkeyPatch):
        stub = _FetchStub([_result(score=60)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        sync_place_images_task("hut", hut.slug)
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1


class TestMaybeEnqueue:
    def _spy(self, monkeypatch: pytest.MonkeyPatch):
        calls = []

        def _fake_async_task(func: Callable[..., Any] | str, *args: Any, **kwargs: Any):
            calls.append((func, args))

        monkeypatch.setattr("django_q.tasks.async_task", _fake_async_task)
        return calls

    def test_never_pinned_enqueues_nothing(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
        calls = self._spy(monkeypatch)
        assert maybe_enqueue_place_refresh(hut) is False
        assert calls == []

    def test_fresh_pins_enqueue_nothing(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
        calls = self._spy(monkeypatch)
        hut.images_pinned_at = timezone.now()
        hut.save(update_fields=["images_pinned_at"])
        assert maybe_enqueue_place_refresh(hut) is False
        assert calls == []

    def test_stale_pins_enqueue_once_then_debounce(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
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
    def test_stale_hut_fast_path_enqueues(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
        from tests.helpers import PrefixedClient as TestClient

        calls = []

        def _fake_async_task(func: Callable[..., Any] | str, *args: Any, **kwargs: Any):
            calls.append((func, args))

        monkeypatch.setattr("django_q.tasks.async_task", _fake_async_task)
        pin_place_images(hut, [_result(score=80)])
        hut.images_pinned_at = timezone.now() - timedelta(days=2)
        hut.save(update_fields=["images_pinned_at"])

        client = TestClient("/v1/geo/images")
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        # The fast path may enqueue several tasks (visit counter, pin
        # refresh, phash assessment) — each exactly once, identified by
        # its task function.
        funcs = [func for func, _args in calls]
        assert funcs.count("server.apps.geometries.pinning.sync_place_images_task") == 1
        assert (
            funcs.count("server.apps.images.assessment.assess_place_task") == 1
        )  # unassessed pins enqueue the background assessment
        refresh_calls = [
            args
            for func, args in calls
            if func == "server.apps.geometries.pinning.sync_place_images_task"
        ]
        assert refresh_calls == [("hut", hut.slug)]
        # Second hit within the debounce window: no new tasks of either kind.
        client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=11")
        assert funcs.count("server.apps.geometries.pinning.sync_place_images_task") == 1
        assert funcs.count("server.apps.images.assessment.assess_place_task") == 1


class TestDeadOriginFlagging:
    def test_dead_origin_moves_to_review(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
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

        def _head(url: str, **kwargs: Any):
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

    def test_live_origin_untouched(self, hut: Hut, monkeypatch: pytest.MonkeyPatch):
        pin_place_images(hut, [_result(source_id="File:Alive.jpg", score=70)])
        stub = _FetchStub([])  # missing from results, but origin is alive

        def _head(url: str, **kwargs: Any):
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
    def test_dry_run_reports(self, hut: Hut, capsys: pytest.CaptureFixture[str]):
        call_command("geoimages_pin", place=hut.slug, dry_run=True)
        out = capsys.readouterr().out
        assert "would sync hut" in out and hut.slug in out

    def test_single_place_sync(self, hut: Hut, monkeypatch: pytest.MonkeyPatch):
        stub = _FetchStub([_result(score=55)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        call_command("geoimages_pin", place=hut.slug)
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1

    def test_unknown_place_raises(self):
        with pytest.raises(CommandError):
            call_command("geoimages_pin", place="nope")

    def test_default_targets_unpinned_only(
        self,
        hut: Hut,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """Default (no args) pins only places never synced from providers."""
        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )

        # Unpinned hut → default mode sweeps it.
        call_command("geoimages_pin")
        out = capsys.readouterr().out
        assert "unpinned only" in out and hut.slug in seen

        # Pinned hut → default mode skips it; --all still sweeps it.
        hut.images_pinned_at = timezone.now()
        hut.save(update_fields=["images_pinned_at"])
        # Deterministic: mark every other place synced too (the test DB may
        # carry unpinned geoplaces from the seed or earlier runs).
        from server.apps.geometries.models import GeoPlace

        GeoPlace.objects.filter(images_pinned_at__isnull=True).update(
            images_pinned_at=timezone.now()
        )
        seen.clear()
        call_command("geoimages_pin")
        out = capsys.readouterr().out
        assert "Nothing to do" in out and hut.slug not in seen

        seen.clear()
        call_command("geoimages_pin", all=True)
        assert hut.slug in seen

    def test_type_filter_applies_to_sweep(
        self,
        hut: Hut,
        seed_data: dict[str, int],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        pin_place_images(place, [_result(score=10)])  # geoplace now has pins
        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )
        call_command("geoimages_pin", all=True, type="hut")
        out = capsys.readouterr().out
        assert hut.slug in seen and place.slug not in seen
        assert "(full sweep)" in out

    def test_bbox_filters_sweep(
        self,
        hut: Hut,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """--bbox restricts the sweep to places inside the envelope."""
        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )

        # A bbox in the Pacific excludes the Alpine seed hut.
        call_command("geoimages_pin", bbox="-179.0,-50.0,-178.0,-49.0")
        out = capsys.readouterr().out
        assert "Nothing to do" in out and "+ bbox" in out and hut.slug not in seen

        # A worldwide bbox includes it.
        seen.clear()
        call_command("geoimages_pin", bbox="-180.0,-90.0,180.0,90.0")
        out = capsys.readouterr().out
        assert hut.slug in seen

    def test_bbox_antimeridian(
        self,
        hut: Hut,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """--bbox crossing the antimeridian works (NZ-style box)."""
        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )

        # The previously-rejected spelling (lons below -180) now parses to
        # a wrapped multipolygon; the Alpine seed hut stays outside it.
        call_command("geoimages_pin", bbox="-202.88683,-51.74934,-160.53732,-30.64888")
        out = capsys.readouterr().out
        assert "Nothing to do" in out and "+ bbox" in out and hut.slug not in seen

    def test_invalid_bbox_raises(self):
        with pytest.raises(CommandError):
            call_command("geoimages_pin", bbox="not,a,bbox")

    def test_bbox_widget_renders(self):
        """Smoke test: widget renders the map, input, and draw toolbar."""
        from server.apps.geometries.widgets import BBoxWidget

        html = BBoxWidget().render("bbox", "7.5,46.0,8.5,46.8")
        assert "bbox-widget" in html
        assert 'name="bbox"' in html and 'value="7.5,46.0,8.5,46.8"' in html
        assert "bbox_widget.js" in html
        assert 'class="bbox-draw-btn"' in html
        assert 'type="button"' in html  # must never submit the run form

    def test_assess_skipped_when_place_has_no_pins(
        self,
        hut: Hut,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """--assess (and warmup) are pointless for places without pins."""
        assessed = []

        def _assess(place: Any, force: bool = False) -> dict[str, int]:
            assessed.append(place.slug)
            return {"assessed": 0}

        monkeypatch.setattr(
            "server.apps.images.assessment.assess_place_pins",
            _assess,
        )
        stub = _FetchStub([])  # no provider results → no pins
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )

        call_command("geoimages_pin", place=hut.slug, assess=True)
        out = capsys.readouterr().out
        assert "assessed pins" not in out and assessed == []

        # Pins exist → assess runs.
        pin_place_images(hut, [_result(score=50)])
        call_command("geoimages_pin", place=hut.slug, assess=True)
        out = capsys.readouterr().out
        assert "assessed pins" in out and hut.slug in assessed

    def test_all_sweep_covers_huts_and_pinned_geoplaces(
        self, hut: Hut, seed_data: dict[str, int], monkeypatch: pytest.MonkeyPatch
    ):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        pin_place_images(place, [_result(score=10)])  # geoplace now has pins

        seen = []

        class _SweepStub(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("place_slug"))
                return [], {"location": {"lat": 1.0, "lon": 1.0}}

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", _SweepStub([])
        )
        call_command("geoimages_pin", all=True)
        assert hut.slug in seen and place.slug in seen

    def test_budget_flag_threads_to_fanout(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch
    ):
        """--budget (seconds) reaches the fan-out; the command default is
        3× the request-path budget (background sweeps wait longer)."""
        seen = []

        class _BudgetRecorder(_FetchStub):
            async def __call__(self, **kwargs: Any) -> tuple[list[Any], dict[str, Any]]:
                seen.append(kwargs.get("budget"))
                return await super().__call__(**kwargs)

        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place",
            _BudgetRecorder([]),
        )
        call_command("geoimages_pin", place=hut.slug)
        call_command("geoimages_pin", place=hut.slug, budget=25)
        with override_settings(IMAGES_FANOUT_BUDGET_SECONDS=5):
            call_command("geoimages_pin", place=hut.slug)
        assert seen == [30.0, 25, 15.0]


class TestImagorWarmup:
    """--warmup-image-cache: metadata-only sync stays, pixels prefetched."""

    def _settings(self, settings: SettingsWrapper):
        settings.IMAGOR_URL = "http://imagor.test"
        settings.IMAGOR_KEY = ""

    def test_warms_preview_and_medium(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper
    ):
        from unittest.mock import MagicMock

        from server.apps.geometries.pinning import warmup_place_image_cache

        self._settings(settings)
        pin_place_images(
            hut, [_result(score=80), _result(source_id="File:B.jpg", score=40)]
        )

        fetched = []
        fake = MagicMock()
        fake.status_code = 200

        def _get(url: str, **kwargs: Any):
            fetched.append(url)
            return fake

        monkeypatch.setattr("requests.get", _get)
        warmed = warmup_place_image_cache(hut)
        assert warmed == 4  # 2 pins x (preview + medium)
        assert all(url.startswith("http://imagor.test/") for url in fetched)
        assert len(fetched) == 4

    def test_dead_origin_ignored(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper
    ):
        from unittest.mock import MagicMock

        from server.apps.geometries.pinning import warmup_place_image_cache

        self._settings(settings)
        pin_place_images(hut, [_result(score=80)])

        fake = MagicMock()
        fake.status_code = 404
        monkeypatch.setattr("requests.get", MagicMock(return_value=fake))
        assert warmup_place_image_cache(hut) == 0  # tolerated, not an error

    def test_command_flag_calls_warmup(
        self, hut: Hut, monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper
    ):
        from unittest.mock import MagicMock

        self._settings(settings)
        stub = _FetchStub([_result(score=55)])
        monkeypatch.setattr(
            "server.apps.geometries.providers.fetch_images_for_place", stub
        )
        warmed = MagicMock(return_value=2)
        monkeypatch.setattr(
            "server.apps.geometries.management.commands.geoimages_pin"
            ".warmup_place_image_cache",
            warmed,
        )
        call_command("geoimages_pin", place=hut.slug, warmup_image_cache=True)
        warmed.assert_called_once()
