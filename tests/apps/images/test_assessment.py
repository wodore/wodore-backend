"""Tests for technical image assessment (phash, quality, thumbhash, duplicates).

All pixel fixtures are generated with PIL/numpy — no network, no models.
"""

import io

import pytest
from PIL import Image as PILImage

from tests.apps.geometries.test_image_pinning import _result

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError

from server.apps.geometries import image_response_cache as irc
from server.apps.geometries.pinning import pin_place_images
from server.apps.images.assessment import (
    DUPLICATE_HAMMING_DISTANCE,
    assess_image,
    assess_place_pins,
    dhash64,
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

    class _Resp:
        status_code = 200
        content = _pil_bytes(_textured())

        def raise_for_status(self):
            return None

        def json(self):
            if "/meta/" in self.url:
                return {"thumbhash": "F/gJNQJXh493Z4lneYqHd4ZwZAk2"}
            return {}

        url = ""

    def _get(url, timeout=None):
        resp = _Resp()
        resp.url = url
        return resp

    monkeypatch.setattr(assessment.requests, "get", _get)


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
        assert image.thumbhash == "F/gJNQJXh493Z4lneYqHd4ZwZAk2"  # from imagor meta
        assert 0 <= image.quality_score <= 100
        assert "sharpness" in image.image_meta["quality"]
        assert "assessed_at" in image.image_meta

    def test_variant_thumbhashes_naming(self):
        image = self._image()  # 1920x1080 landscape
        assert assess_image(image) is True
        hashes = image.image_meta["thumbhashes"]
        assert set(hashes) == {
            "thumb_square",
            "thumb_landscape",
            "thumb_portrait",
            "preview_square",
            "preview_landscape",
            "preview_portrait",
        }

    def test_skips_already_assessed(self):
        image = self._image()
        assert assess_image(image) is True
        assert assess_image(image) is False  # cached, not recomputed
        assert assess_image(image, force=True) is True


class TestCommand:
    def test_default_assesses_pinned_places(self, hut, capsys):
        """Default (no args) sweeps every place that has pins."""
        pin_place_images(hut, [_result(score=80)])
        call_command("geoimages_assess", no_progress=True)
        out = capsys.readouterr().out
        assert f"assessed hut:{hut.slug}" in out
        assert "(all pinned places)" in out

    def test_no_pins_reports_nothing_to_do(self, hut, capsys):
        call_command("geoimages_assess")
        out = capsys.readouterr().out
        assert "Nothing to do" in out

    def test_bbox_filters_targets(self, hut, monkeypatch, capsys):
        """A tiny bbox elsewhere on the globe excludes the pinned place."""
        pin_place_images(hut, [_result(score=80)])
        # hut is in the Alps; a bbox in the Pacific matches nothing.
        call_command("geoimages_assess", bbox="-179.0,-50.0,-178.0,-49.0", dry_run=True)
        out = capsys.readouterr().out
        assert "Nothing to do" in out and hut.slug not in out

        # A huge bbox includes it.
        call_command("geoimages_assess", bbox="-180.0,-90.0,180.0,90.0", dry_run=True)
        out = capsys.readouterr().out
        assert f"would assess hut:{hut.slug}" in out

    def test_invalid_bbox_raises(self):
        with pytest.raises(CommandError):
            call_command("geoimages_assess", bbox="not,a,bbox")

    def test_dry_run(self, hut, capsys):
        call_command("geoimages_assess", place=hut.slug, dry_run=True)
        assert "would assess" in capsys.readouterr().out

    def test_assesses_place(self, hut):
        pin_place_images(hut, [_result(score=80)])
        call_command("geoimages_assess", place=hut.slug)
        image = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        assert image.phash and image.thumbhash


class TestThumbhashDecoder:
    def test_decodes_live_hash(self):
        from server.apps.images.assessment import thumbhash_to_image

        image = thumbhash_to_image("F/gJNQJXh493Z4lneYqHd4ZwZAk2")
        assert image.mode == "RGBA"
        assert image.size[1] == 32  # portrait ratio caps height at 32
        assert image.size[0] < image.size[1]


class TestThumbCropPrecedence:
    def test_thumb_prefers_focal_over_crop(self):
        from server.apps.geometries.providers.base import (
            ImageArea,
            ImageResult,
            post_process_images,
        )

        result = ImageResult(
            provider="wikicommons",
            source_id="File:P.jpg",
            source_url=None,
            image_type="flat",
            captured_at=None,
            location=Point(7.5, 46.5),
            distance_m=0.0,
            license_slug="cc-by-sa-4-0",
            attribution="x",
            author=None,
            author_url=None,
            url_large="https://upload.wikimedia.org/x/P.jpg",
            width=1920,
            height=1080,
            focal=ImageArea(x1=0.1, y1=0.1, x2=0.5, y2=0.5),
            crop=ImageArea(x1=0.0, y1=0.0, x2=0.8, y2=1.0),
        )
        features = post_process_images([result])
        urls = features[0]["properties"]["urls"]
        xs = urls["landscape"]["xs"]
        sm = urls["landscape"]["sm"]
        md = urls["landscape"]["md"]
        assert "0.10x0.10:0.50x0.50" in xs  # focal area crops xs
        assert "0.10x0.10:0.50x0.50" in sm  # focal area crops sm too
        assert "0.00x0.00:0.80x1.00" in md  # curated crop applies to md+
        assert "0.10x0.10:0.50x0.50" not in md.split("filters:")[0]


class TestAdminSaveHook:
    def test_save_triggers_reassessment(self, admin_client, settings, monkeypatch):
        from unittest.mock import patch

        from django.conf import settings as dj_settings

        from server.apps.licenses.models import License

        settings.MIDDLEWARE = tuple(
            m for m in dj_settings.MIDDLEWARE if "debug_toolbar" not in m
        )
        license_obj, _ = License.objects.get_or_create(
            slug="cc-by-sa-4-0", defaults={"no_publication": False}
        )
        image = Image.objects.create(
            source_ident="wikicommons:File:Hook.jpg",
            source_url_raw="https://upload.wikimedia.org/x/Hook.jpg",
            license=license_obj,
        )
        with patch(
            "server.apps.images.assessment.assess_image", return_value=True
        ) as mock_assess:
            response = admin_client.post(
                f"/admin/images/image/{image.id}/change/",
                {
                    "source_url": "https://example.org/hut",
                    "license": str(license_obj.id),  # pyright: ignore[reportAttributeAccessIssue]
                    "caption_en": "x",
                    "review_status": "approved",
                    "_continue": "1",
                },
            )
        assert response.status_code in (200, 302)
        mock_assess.assert_called_once()
        assert mock_assess.call_args.kwargs.get("force") is True


class TestAssessPlace:
    def test_duplicates_marked_weaker_twin(self, hut, monkeypatch):
        # Two pins whose fetch returns the same pixels, plus one smooth
        # gradient (guaranteed far from noise in dhash space).
        import numpy as np

        from server.apps.images import assessment

        gradient = PILImage.fromarray(
            np.tile(np.linspace(0, 255, 360, dtype=np.uint8), (240, 1))[
                :, :, None
            ].repeat(3, axis=2)
        )
        payloads = [
            _pil_bytes(_textured(seed=1)),
            _pil_bytes(_textured(seed=1)),  # near-duplicate
            _pil_bytes(gradient),
        ]
        calls = {"n": 0}

        def _fake_get(url, timeout=None):
            if "/meta/" in url:  # thumbhash metadata request

                class _Meta:
                    status_code = 200

                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"thumbhash": "F/gJNQJXh493Z4lneYqHd4ZwZAk2"}

                return _Meta()

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
        twin_a = Image.objects.get(source_ident="wikicommons:File:Test.jpg")
        twin_b = Image.objects.get(source_ident="wikicommons:File:Duplicate.jpg")
        marked = [img for img in (twin_a, twin_b) if img.image_meta.get("duplicate_of")]
        unmarked = [
            img for img in (twin_a, twin_b) if not img.image_meta.get("duplicate_of")
        ]
        assert len(marked) == 1 and len(unmarked) == 1  # exactly one twin marked
        assert marked[0].image_meta["duplicate_of"] == unmarked[0].source_ident
        distinct = Image.objects.get(source_ident="wikicommons:File:Distinct.jpg")
        assert not distinct.image_meta.get("duplicate_of")


class TestResponsePassthrough:
    def test_thumbhashes_in_features(self, hut, monkeypatch):
        from tests.helpers import PrefixedClient as TestClient

        pin_place_images(hut, [_result(score=80)])
        assess_place_pins(hut)
        client = TestClient("/v1/geo/images")
        response = client.get(f"/hut/{hut.slug}?radius=50&lang=en&limit=10")
        assert response.status_code == 200
        props = response.json()["features"][0]["properties"]
        assert props["thumbhashes"]["thumb_square"] == "F/gJNQJXh493Z4lneYqHd4ZwZAk2"
