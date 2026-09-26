"""Tests for pinning external provider results (spec: external-image-pinning).

Covers the pin service (dedupe across syncs, score semantics, internal-result
skipping, metadata merge) and the endpoint fast path / lazy write-through.
"""

import pytest
from ninja.testing import TestClient

from django.contrib.gis.geos import Point

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.api_images import router
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
        return TestClient(router)

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
        assert scores == sorted(scores, reverse=True)

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
        assert hut_assoc.score == 90
        assert place_assoc.score == 40  # per-place curation


class TestPlaceEndpointPins:
    """images_for_place gets the same pins fast path / lazy write-through."""

    @pytest.fixture
    def client(self):
        return TestClient(router)

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
