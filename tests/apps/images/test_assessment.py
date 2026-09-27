"""Tests for technical image assessment (phash, quality, blurhash, duplicates).

All pixel fixtures are generated with PIL/numpy — no network, no models.
"""

import io

import pytest
from PIL import Image as PILImage

from tests.apps.geometries.test_image_pinning import _result

from django.core.management import call_command
from django.core.management.base import CommandError

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.pinning import pin_place_images
from server.apps.images.assessment import (
    DUPLICATE_HAMMING_DISTANCE,
    assess_image,
    assess_place_pins,
    dhash64,
    encode_blurhash,
    hamming_distance,
    quality_metrics,
    technical_score,
)
from server.apps.images.models import Image

pytestmark = pytest.mark.django_db


def _pil_bytes(image: PILImage.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def _textured(seed: int = 42, shift: int = 0) -> PILImage.Image:
    import numpy as np

    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (240, 360, 3), dtype=np.uint8)
    if shift:
        arr = np.roll(arr, shift, axis=1)
    return PILImage.fromarray(arr.copy())


def _blurred(image: PILImage.Image) -> PILImage.Image:
    from PIL import ImageFilter

    return image.filter(ImageFilter.GaussianBlur(radius=6))


class TestPrimitives:
    def test_dhash_format_and_stability(self):
        image = _textured()
        digest = dhash64(image)
        assert len(digest) == 16
        assert digest == dhash64(image)  # deterministic
        assert digest != dhash64(_textured(seed=7))

    def test_near_duplicate_within_threshold(self):
        original = dhash64(_textured())
        shifted = dhash64(_textured(shift=3))
        unrelated = dhash64(_textured(seed=99))
        assert hamming_distance(original, shifted) <= DUPLICATE_HAMMING_DISTANCE
        assert hamming_distance(original, unrelated) > DUPLICATE_HAMMING_DISTANCE

    def test_blurhash_format(self):
        digest = encode_blurhash(_textured())
        assert len(digest) == 28  # 4x3 components: 6 + 2*11 base-83 chars
        assert digest == encode_blurhash(_textured())  # deterministic
        assert digest != encode_blurhash(_textured(seed=7))

    def test_quality_sharp_beats_blurred(self):
        sharp = quality_metrics(_textured())
        blurry = quality_metrics(_blurred(_textured()))
        assert sharp["sharpness"] > blurry["sharpness"] * 5

    def test_technical_score_ordering(self):
        sharp = technical_score(quality_metrics(_textured()), 1920, 1080)
        blurry = technical_score(quality_metrics(_blurred(_textured())), 1920, 1080)
        small = technical_score(quality_metrics(_textured()), 400, 300)
        assert sharp > blurry
        assert sharp > small


@pytest.fixture
def hut(seed_data):
    from server.apps.huts.models import Hut, HutImageAssociation

    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    return hut


@pytest.fixture(autouse=True)
def _isolated_response_cache(monkeypatch):
    """Private locmem response cache (the persistent DB cache is shared)."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    monkeypatch.setattr(irc, "_cache", lambda: LocMemCache(f"test-{uuid4().hex}", {}))


@pytest.fixture(autouse=True)
def _imagor(settings, monkeypatch):
    """Deterministic imagor URLs; pixel bytes served by a fake requests.get."""
    from server.apps.images import assessment

    settings.IMAGOR_URL = "http://imagor.test"
    settings.IMAGOR_KEY = ""

    def _fake_get(url, timeout=None):
        class _Resp:
            status_code = 200
            content = _pil_bytes(_textured())

            def raise_for_status(self):
                return None

        return _Resp()

    monkeypatch.setattr(assessment.requests, "get", _fake_get)


class TestAssessImage:
    def _image(self):
        from server.apps.licenses.models import License

        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        return Image.objects.create(
            source_ident="wikicommons:File:Assess.jpg",
            source_url_raw=(
                "https://upload.wikimedia.org/wikipedia/commons/thumb/Assess.jpg"
            ),
            image_meta={"width": 1920, "height": 1080},
            license=license_obj,
        )

    def test_writes_columns_and_meta(self):
        image = self._image()
        assert assess_image(image) is True
        assert len(image.phash) == 16
        assert len(image.blurhash) == 28
        assert 0 <= image.quality_score <= 100
        assert "sharpness" in image.image_meta["quality"]
        assert "assessed_at" in image.image_meta

    def test_skips_already_assessed(self):
        image = self._image()
        assert assess_image(image) is True
        assert assess_image(image) is False  # cached, not recomputed
        assert assess_image(image, force=True) is True


class TestAssessPlace:
    def test_duplicates_marked_weaker_twin(self, hut, monkeypatch):
        from server.apps.images import assessment

        # Two pins whose fetch returns the same pixels, plus one distinct.
        payloads = [
            _pil_bytes(_textured(seed=1)),
            _pil_bytes(_textured(seed=1)),  # near-duplicate
            _pil_bytes(_textured(seed=2)),
        ]
        calls = {"n": 0}

        def _fake_get(url, timeout=None):
            class _Resp:
                status_code = 200
                content = payloads[calls["n"] % 3]

                def raise_for_status(self):
                    return None

            resp = _Resp()
            calls["n"] += 1
            return resp

        monkeypatch.setattr(assessment.requests, "get", _fake_get)
        pin_place_images(
            hut,
            [
                _result(score=80, url="https://upload.wikimedia.org/a/A.jpg"),
                _result(
                    source_id="File:Duplicate.jpg",
                    url="https://upload.wikimedia.org/a/B.jpg",
                    score=70,
                ),
                _result(
                    source_id="File:Distinct.jpg",
                    url="https://upload.wikimedia.org/a/C.jpg",
                    score=60,
                ),
            ],
        )
        stats = assess_place_pins(hut)
        assert stats["duplicates"] == 1
        dup = Image.objects.get(source_ident="wikicommons:File:Duplicate.jpg")
        assert dup.image_meta["duplicate_of"] == "wikicommons:File:Test.jpg"
        distinct = Image.objects.get(source_ident="wikicommons:File:Distinct.jpg")
        assert "duplicate_of" not in distinct.image_meta


class TestResponsePassthrough:
    def test_blurhash_first_class_in_features(self, hut, monkeypatch):
        from ninja.testing import TestClient

        from server.apps.geometries.api_images import router

        pin_place_images(hut, [_result(score=80)])
        assess_place_pins(hut)
        client = TestClient(router)
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        props = response.json()["features"][0]["properties"]
        assert len(props["blurhash"]) == 28  # first-class, not nested
        assert "quality_score" in props["extra"]


class TestCommand:
    def test_requires_scope(self):
        with pytest.raises(CommandError):
            call_command("geoimages_assess")

    def test_dry_run(self, hut, capsys):
        call_command("geoimages_assess", place=hut.slug, dry_run=True)
        assert "would assess" in capsys.readouterr().out

    def test_assesses_place(self, hut):
        pin_place_images(hut, [_result(score=80)])
        call_command("geoimages_assess", place=hut.slug)
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.phash and image.blurhash
