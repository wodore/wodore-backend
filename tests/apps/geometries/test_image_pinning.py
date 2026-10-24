"""Tests for pinning external provider results (spec: external-image-pinning).
Covers the pin service (dedupe across syncs, score semantics, internal-result
skipping, metadata merge) and the endpoint fast path / lazy write-through.
"""

from datetime import UTC, datetime

import pytest

from tests.helpers import PrefixedClient as TestClient

from django.contrib.gis.geos import Point
from django.utils import timezone

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.pinning import pin_place_images, place_has_visible_pins
from server.apps.geometries.providers.base import ImageResult
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Private locmem response cache per test (no database cache leakage)."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    cache = LocMemCache(f"test-{uuid4().hex}", {})
    monkeypatch.setattr(irc, "_cache", lambda: cache)


def _result(
    provider: str = "wikicommons",
    source_id: str = "File:Test.jpg",
    score: int = 80,
    url: str = "https://upload.wikimedia.org/wikipedia/commons/thumb/Test_1920.jpg",
    extra: dict | None = None,
) -> ImageResult:
    return ImageResult(
        provider=provider,
        source_id=source_id,
        source_url=f"https://commons.wikimedia.org/wiki/{source_id}",
        image_type="flat",
        captured_at=None,
        location=Point(7.5, 46.5),
        distance_m=42.0,
        license_slug="cc-by-sa-4-0",
        attribution="Test Author, CC BY-SA",
        author="Test Author",
        author_url=None,
        url_large=url,
        width=1920,
        height=1080,
        score=score,
        extra=extra,
    )


@pytest.fixture
def hut(seed_data):
    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    # Start from a clean, unpinned state.
    HutImageAssociation.objects.filter(hut=hut).delete()
    hut.images_pinned_at = None
    hut.save(update_fields=["images_pinned_at"])
    return hut


class TestPinService:
    def test_creates_image_and_association(self, hut):
        stats = pin_place_images(
            hut, [_result(score=80), _result(source_id="File:Other.jpg", score=60)]
        )
        assert stats.created == 2
        assert stats.associations_created == 2
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.source_url_raw == _result().url_large
        assert image.image_meta["provider_score"] == 80
        assert image.image_meta["width"] == 1920
        assert image.provider_synced_at is not None
        assert image.image.name == ""  # metadata only — nothing hosted
        assert HutImageAssociation.objects.get(image=image, hut=hut).score == 80
        hut.refresh_from_db()
        assert hut.images_pinned_at is not None

    def test_resync_updates_instead_of_duplicating(self, hut):
        pin_place_images(hut, [_result()])
        new_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/Test_3840.jpg"
        stats = pin_place_images(hut, [_result(url=new_url, score=90)])
        assert stats.created == 0
        assert stats.updated == 1
        assert (
            Image.objects.filter(source_ident="wikicommons:File:Test.jpg").count() == 1
        )
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.source_url_raw == new_url
        assert image.image_meta["provider_score"] == 90

    def test_manual_score_survives_sync(self, hut):
        pin_place_images(hut, [_result(score=80)])
        assoc = HutImageAssociation.objects.get(
            hut=hut, image__source_ident="wikicommons:File:Test.jpg"
        )
        assoc.score = 1  # curator pushes the image to the back
        assoc.save()
        pin_place_images(hut, [_result(score=95)])
        assoc.refresh_from_db()
        assert assoc.score == 1  # never overwritten

    def test_internal_results_skipped(self, hut):
        stats = pin_place_images(
            hut, [_result(provider="wodore", source_id="some-uuid")]
        )
        assert stats.skipped == 1
        assert stats.created == 0
        assert not HutImageAssociation.objects.filter(hut=hut).exists()

    def test_internal_pin_passthrough_skipped(self, hut):
        """Provider passthroughs of existing pins must not be re-pinned.

        WodoreProvider reports pins with provider = source_org slug and
        source_id = the row's source_ident; re-pinning minted a new Image
        with the provider prefix stacked onto the ident and a duplicate
        association — every sync doubled every visible pin (staging 2026-10).
        """
        pin_place_images(
            hut, [_result(provider="camptocamp", source_id="waypoint_1_a.jpg")]
        )
        passthrough = _result(
            provider="camptocamp",
            source_id="camptocamp:waypoint_1_a.jpg",
            extra={"internal_pin": True},
        )
        stats = pin_place_images(hut, [passthrough])
        assert stats.skipped == 1
        assert stats.created == 0
        assert not Image.objects.filter(
            source_ident="camptocamp:camptocamp:waypoint_1_a.jpg"
        ).exists()
        assert HutImageAssociation.objects.filter(hut=hut).count() == 1

    def test_internal_pin_passthrough_skipped_for_geoplaces(self):
        """Same guard on the GeoPlace path — pins stay single there too."""
        from tests.factories.geometries import GeoPlaceFactory

        from server.apps.geometries.models import GeoPlaceImageAssociation

        place = GeoPlaceFactory(slug="pin-dupe-place")
        pin_place_images(
            place,
            [_result(provider="camptocamp", source_id="waypoint_2_b.jpg")],
        )
        passthrough = _result(
            provider="camptocamp",
            source_id="camptocamp:waypoint_2_b.jpg",
            extra={"internal_pin": True},
        )
        stats = pin_place_images(place, [passthrough])
        assert stats.skipped == 1
        assert GeoPlaceImageAssociation.objects.filter(geo_place=place).count() == 1
        assert not Image.objects.filter(
            source_ident="camptocamp:camptocamp:waypoint_2_b.jpg"
        ).exists()

    def test_provider_scores_clamped_to_pin_band(self, hut):
        """Provider pins stay ≤ 89 — curated uploads own 90–99, and the
        image endpoints validate scores against the API contract (0–100)."""
        pin_place_images(
            hut, [_result(score=95), _result(source_id="File:Mid.jpg", score=50)]
        )
        strong = HutImageAssociation.objects.get(
            hut=hut, image__source_ident="wikicommons:File:Test.jpg"
        )
        mid = HutImageAssociation.objects.get(
            hut=hut, image__source_ident="wikicommons:File:Mid.jpg"
        )
        assert strong.score == 89
        assert mid.score == 50

    def test_meta_merge_preserves_curated_focal(self, hut):
        pin_place_images(hut, [_result()])
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        image.image_meta["focal"] = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}
        image.save(update_fields=["image_meta"])
        pin_place_images(hut, [_result(score=70)])
        image.refresh_from_db()
        assert image.image_meta["focal"] == {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}
        assert image.image_meta["provider_score"] == 70  # refreshed


class _FetchStub:
    def __init__(self):
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        results = [
            _result(score=80),
            _result(source_id="File:Second.jpg", score=65),
            _result(provider="wodore", source_id="internal-uuid", score=50),
        ]
        return results, {"location": {"lat": 46.5, "lon": 7.5}}


class TestPinsEndpoint:
    @pytest.fixture
    def client(self):
        return TestClient("/v1/geo/images")

    @pytest.fixture
    def fetch(self, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub()
        monkeypatch.setattr(api_images, "fetch_images_for_place", stub)
        return stub

    def test_fast_path_never_calls_providers(self, client, hut, fetch, monkeypatch):
        from server.apps.geometries import api_images

        def _boom(**kwargs):
            raise AssertionError("live path must not run when pins exist")

        monkeypatch.setattr(api_images, "fetch_images_for_place", _boom)
        pin_place_images(
            hut, [_result(score=80), _result(source_id="File:Low.jpg", score=30)]
        )
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        providers = [
            f["properties"]["provider"]["slug"] for f in response.json()["features"]
        ]
        assert providers  # served entirely from pins
        # Highest score first (association score drives the order).
        scores = [
            HutImageAssociation.objects.get(
                hut=hut,
                image__source_ident=f["properties"]["source_id"],
            ).score
            for f in response.json()["features"]
        ]
        assert scores == sorted(scores, reverse=True)  # type: ignore  # optional pks sorted in test

    def test_lazy_pins_on_first_visit(self, client, hut, fetch):
        assert not place_has_visible_pins(hut)
        first = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert first.status_code == 200
        assert fetch.calls == 1
        # Two external results pinned; the internal wodore result skipped.
        assert Image.objects.filter(provider_synced_at__isnull=False).count() == 2
        assert place_has_visible_pins(hut)
        hut.refresh_from_db()
        assert hut.images_pinned_at is not None
        second = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert second.status_code == 200
        assert fetch.calls == 1  # second request served without the live path

    def test_update_cache_forces_repin(self, client, hut, fetch):
        client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert fetch.calls == 1
        client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10&update_cache=true")
        assert fetch.calls == 2  # forced refresh re-ran the live pipeline
        # And the pins are still there (refreshed, not duplicated).
        assert Image.objects.filter(provider_synced_at__isnull=False).count() == 2

    def test_sources_bypasses_pin_path(self, client, hut, fetch):
        pin_place_images(hut, [_result()])
        response = client.get(
            f"/hut/{hut.slug}?radius=50&lang=en&limit=10&sources=wikicommons"
        )
        assert response.status_code == 200
        assert fetch.calls == 1  # explicit provider selection goes live

    def test_hidden_pin_excluded(self, client, hut, fetch):
        pin_place_images(
            hut, [_result(score=80), _result(source_id="File:Hidden.jpg", score=70)]
        )
        image = Image.objects.get(source_ident="wikicommons:File:Hidden.jpg")
        image.review_status = Image.ReviewStatusChoices.rejected
        image.save(update_fields=["review_status"])
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert "wikicommons:File:Hidden.jpg" not in source_ids
        assert "wikicommons:File:Test.jpg" in source_ids


class TestPinGeoplace:
    """The pin service is place-generic (huts and geoplaces share it)."""

    def test_pins_geoplace(self, seed_data):
        from server.apps.geometries.models import GeoPlace, GeoPlaceImageAssociation

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None, "seed data provides no public geoplace"
        stats = pin_place_images(place, [_result(score=70)])
        assert stats.created == 1
        assoc = GeoPlaceImageAssociation.objects.get(
            geo_place=place, image__source_ident="wikicommons:File:Test.jpg"
        )
        assert assoc.score == 70
        place.refresh_from_db()
        assert place.images_pinned_at is not None
        assert place_has_visible_pins(place)

    def test_same_image_two_places_independent_scores(self, hut, seed_data):
        from server.apps.geometries.models import GeoPlace

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        pin_place_images(hut, [_result(score=90)])
        stats = pin_place_images(place, [_result(score=40)])
        assert stats.created == 0  # same Image row reused
        assert stats.associations_created == 1
        assert (
            Image.objects.filter(source_ident="wikicommons:File:Test.jpg").count() == 1
        )
        hut_assoc = HutImageAssociation.objects.get(
            hut=hut, image__source_ident="wikicommons:File:Test.jpg"
        )
        from server.apps.geometries.models import GeoPlaceImageAssociation

        place_assoc = GeoPlaceImageAssociation.objects.get(
            geo_place=place, image__source_ident="wikicommons:File:Test.jpg"
        )
        # Provider scores above the pin band clamp to 89 — curated uploads
        # (90–99) always outrank pins (see HutImageAssociation).
        assert hut_assoc.score == 89
        assert place_assoc.score == 40  # per-place curation


class TestPlaceEndpointPins:
    """images_for_place gets the same pins fast path / lazy write-through."""

    @pytest.fixture
    def client(self):
        return TestClient("/v1/geo/images")

    @pytest.fixture
    def place(self, seed_data):
        from server.apps.geometries.models import GeoPlace, GeoPlaceImageAssociation

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        GeoPlaceImageAssociation.objects.filter(geo_place=place).delete()
        place.images_pinned_at = None
        place.save(update_fields=["images_pinned_at"])
        return place

    @pytest.fixture
    def fetch(self, monkeypatch):
        from server.apps.geometries import api_images

        stub = _FetchStub()
        monkeypatch.setattr(api_images, "fetch_images_for_place", stub)
        return stub

    def test_lazy_pins_on_first_visit(self, client, place, fetch):
        response = client.get(f"/place/{place.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        assert fetch.calls == 1
        assert place_has_visible_pins(place)
        assert Image.objects.filter(provider_synced_at__isnull=False).count() == 2
        second = client.get(f"/place/{place.slug}?radius=50&lang=en&limit=9")
        assert second.status_code == 200
        assert fetch.calls == 1  # pins fast path, no live pipeline

    def test_fast_path_serves_pins_by_score(self, client, place, fetch, monkeypatch):
        from server.apps.geometries import api_images

        def _boom(**kwargs):
            raise AssertionError("live path must not run when pins exist")

        monkeypatch.setattr(api_images, "fetch_images_for_place", _boom)
        pin_place_images(
            place, [_result(score=80), _result(source_id="File:Low.jpg", score=10)]
        )
        response = client.get(f"/place/{place.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert source_ids[0] == "wikicommons:File:Test.jpg"  # highest score first

    def test_update_cache_forces_repin(self, client, place, fetch):
        client.get(f"/place/{place.slug}?radius=50&lang=en&limit=10")
        assert fetch.calls == 1
        client.get(f"/place/{place.slug}?radius=50&lang=en&limit=10&update_cache=true")
        assert fetch.calls == 2


class TestServeTimeDedup:
    """Phash-marked near-duplicates (``image_meta.duplicate_of``) are
    dropped at serve time — but only while their primary is served too."""

    @pytest.fixture
    def client(self):
        return TestClient("/v1/geo/images")

    @pytest.fixture(autouse=True)
    def _no_q2(self, monkeypatch):
        """The visit path enqueues background tasks; keep tests deterministic."""
        monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **k: None)

    def _marked_twin(self, place, primary_ident="wikicommons:File:Test.jpg"):
        """Pin a primary + weaker twin, mark the twin like assess_place_pins."""
        twin_ident = "wikicommons:File:Duplicate.jpg"
        pin_place_images(
            place,
            [
                _result(score=80),
                _result(source_id="File:Duplicate.jpg", score=70),
            ],
        )
        twin = Image.objects.get(source_ident=twin_ident)
        meta = dict(twin.image_meta)
        meta["duplicate_of"] = primary_ident
        twin.image_meta = meta
        twin.save(update_fields=["image_meta"])
        return twin

    def test_hut_marked_duplicate_filtered(self, client, hut):
        self._marked_twin(hut)
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert "wikicommons:File:Test.jpg" in source_ids
        assert "wikicommons:File:Duplicate.jpg" not in source_ids

    def test_place_marked_duplicate_filtered(self, client, seed_data):
        from server.apps.geometries.models import (
            GeoPlace,
            GeoPlaceImageAssociation,
        )

        place = GeoPlace.objects.filter(is_active=True, is_public=True).first()
        assert place is not None
        GeoPlaceImageAssociation.objects.filter(geo_place=place).delete()
        self._marked_twin(place)
        response = client.get(f"/place/{place.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert "wikicommons:File:Duplicate.jpg" not in source_ids
        assert "wikicommons:File:Test.jpg" in source_ids

    def test_orphaned_marker_keeps_image(self, client, hut):
        """Primary gone (curator unpinned it) → the twin must stay visible."""
        self._marked_twin(hut)
        HutImageAssociation.objects.filter(
            hut=hut, image__source_ident="wikicommons:File:Test.jpg"
        ).delete()
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert "wikicommons:File:Duplicate.jpg" in source_ids

    def test_unmarked_pins_untouched(self, client, hut):
        """Without the assessment marker both pins serve (status quo)."""
        pin_place_images(
            hut, [_result(score=80), _result(source_id="File:Other.jpg", score=70)]
        )
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        source_ids = [f["properties"]["source_id"] for f in response.json()["features"]]
        assert len(source_ids) == 2


class TestCaptureDateAwareness:
    """Providers may hand through naive capture times (EXIF carries no
    zone) — the pin boundary must store timezone-aware values, else Django
    warns and stores an ambiguously-interpreted datetime."""

    def test_naive_capture_time_pinned_aware(self, hut, recwarn):
        result = _result()
        result.captured_at = datetime(2019, 6, 1, 11, 1, 41)  # noqa: DTZ001 — naive, like Commons
        stats = pin_place_images(hut, [result])
        assert stats.created == 1
        assert not [w for w in recwarn if "naive datetime" in str(w.message)]
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.capture_date is not None
        assert timezone.is_aware(image.capture_date)

    def test_naive_capture_time_refresh_stays_aware(self, hut):
        result = _result()
        result.captured_at = datetime(2019, 6, 1, 11, 1, 41)  # noqa: DTZ001
        pin_place_images(hut, [result])
        result.captured_at = datetime(2020, 7, 2, 12, 2, 42)  # noqa: DTZ001
        stats = pin_place_images(hut, [result])
        assert stats.updated == 1
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.capture_date is not None
        assert timezone.is_aware(image.capture_date)
        assert image.capture_date.year == 2020

    def test_aware_capture_time_untouched(self, hut):
        aware = datetime(2019, 6, 1, 11, 1, 41, tzinfo=UTC)
        result = _result()
        result.captured_at = aware
        pin_place_images(hut, [result])
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.capture_date == aware

    def test_missing_capture_time_stays_none(self, hut):
        pin_place_images(hut, [_result()])
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.capture_date is None


class TestUrlSanitization:
    """Provider URLs must be storable (URLField) and cache-stable."""

    def test_encodes_spaces_and_umlauts(self):
        from server.apps.geometries.pinning import _sanitize_url

        assert _sanitize_url(
            "https://commons.wikimedia.org/wiki/File:Trail signs near Lämmerenhutte.jpg"
        ) == (
            "https://commons.wikimedia.org/wiki/"
            "File:Trail%20signs%20near%20L%C3%A4mmerenhutte.jpg"
        )

    def test_strips_utm_params_keeps_real_ones(self):
        from server.apps.geometries.pinning import _sanitize_url

        assert (
            _sanitize_url(
                "https://upload.wikimedia.org/x.jpg?utm_source=commons.wikimedia.org&width=400"
            )
            == "https://upload.wikimedia.org/x.jpg?width=400"
        )

    def test_already_encoded_untouched(self):
        from server.apps.geometries.pinning import _sanitize_url

        url = (
            "https://upload.wikimedia.org/6/68/Trail_signs_near_L%C3%A4mmerenhutte.jpg"
        )
        assert _sanitize_url(url) == url

    def test_empty(self):
        from server.apps.geometries.pinning import _sanitize_url

        assert _sanitize_url(None) == ""
        assert _sanitize_url("") == ""

    def test_pinned_urls_are_sanitized(self, hut):
        raw_result = _result(
            source_id="File:Trail signs.jpg",
            url=(
                "https://upload.wikimedia.org/x/Trail_signs.jpg"
                "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo"
            ),
        )
        raw_result.source_url = (
            "https://commons.wikimedia.org/wiki/File:Trail signs.jpg"
        )
        pin_place_images(hut, [raw_result])
        image = Image.objects.get(source_ident="wikicommons:File:Trail signs.jpg")
        assert image.source_url == (
            "https://commons.wikimedia.org/wiki/File:Trail%20signs.jpg"
        )
        assert image.source_url_raw == "https://upload.wikimedia.org/x/Trail_signs.jpg"
        from django.core.validators import URLValidator

        URLValidator()(image.source_url)
        URLValidator()(image.source_url_raw)


class TestDefaultCaption:
    def test_caption_cleaned_from_source_id(self, hut):
        pin_place_images(hut, [_result(source_id="File:Trail signs near X.jpg")])
        image = Image.objects.get(
            source_ident="wikicommons:File:Trail signs near X.jpg"
        )
        assert image.caption_en == "Trail signs near X"  # type: ignore[attr-defined]  # modeltrans-generated

    def test_caption_optional(self, seed_data):
        from server.apps.images.models import Image, License

        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        image = Image.objects.create(license=license_obj)  # no caption, no file
        image.refresh_from_db()
        assert image.caption == "" or image.caption is None
