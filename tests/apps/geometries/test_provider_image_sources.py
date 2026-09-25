"""Tests for image source selection (thumb URLs instead of originals).

Wikimedia originals fetched through imagor trip 429s and half-decode large
files (TIFF) into gray thumbnails. Providers therefore expose thumb-based
sources via ``ImageResult.url_medium`` / ``url_large``, and post-processing
builds each display variant from the smallest suitable source.
"""

from typing import Any
from urllib.parse import quote

import pytest

from django.contrib.gis.geos import Point

from server.apps.geometries.providers import base as providers_base
from server.apps.geometries.providers.base import (
    MEDIUM_SOURCE_MAX_DIMENSION,
    ImageResult,
    _calculate_constrained_size,
    post_process_images,
)
from server.apps.geometries.providers.wikimedia_commons import (
    WIKIMEDIA_MEDIUM_THUMB_WIDTH,
    WIKIMEDIA_THUMB_MAX_WIDTH,
    WIKIMEDIA_TIFF_THUMB_MAX_WIDTH,
    WikimediaCommonsProvider,
    _wikimedia_thumb_url,
)

ORIGINAL_URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Huette.jpg"
THUMB_500_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/"
    "Huette.jpg/500px-Huette.jpg"
)


class TestWikimediaThumbUrl:
    def test_rewrites_width_segment(self):
        assert (
            _wikimedia_thumb_url(THUMB_500_URL, 1920)
            == "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/"
            "Huette.jpg/1920px-Huette.jpg"
        )

    def test_replaces_any_cached_width(self):
        """Cached metadata from the old 400px requests must still resolve."""
        cached = THUMB_500_URL.replace("500px-", "400px-")
        assert _wikimedia_thumb_url(cached, 1920) == _wikimedia_thumb_url(
            THUMB_500_URL, 1920
        )

    def test_only_first_width_segment_is_replaced(self):
        url = THUMB_500_URL.replace(
            "Huette.jpg/500px-", "Huette.jpg/500px-"
        )  # single segment by construction
        assert "3000px-" in _wikimedia_thumb_url(url, 3000)


def _image_result(**overrides: Any) -> ImageResult:
    defaults: dict[str, Any] = dict(
        provider="wikicommons",
        source_id="File:Huette.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:Huette.jpg",
        image_type="flat",
        captured_at=None,
        location=Point(7.5, 46.5, srid=4326),
        distance_m=0.0,
        license_slug="cc-by-sa-4.0",
        attribution="Author, Wikimedia Commons",
        author="Author",
        author_url=None,
        url_large=ORIGINAL_URL,
        url_medium=None,
        width=4000,
        height=3000,
    )
    defaults.update(overrides)
    return ImageResult(**defaults)


def _img_data(**overrides) -> dict:
    defaults = dict(
        url=ORIGINAL_URL,
        thumb_url=THUMB_500_URL,
        width=4000,
        height=3000,
        size=5_000_000,
        mime="image/jpeg",
        author="Author",
        author_url=None,
        license="cc-by-sa-4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0",
        description="A hut",
        date_taken="2023-08-15 12:00:00",
        categories=[],
        is_featured=False,
        is_quality=False,
    )
    defaults.update(overrides)
    return defaults


class TestCreateImageResultSources:
    @pytest.fixture
    def provider(self):
        return WikimediaCommonsProvider()

    def _create(self, provider, **overrides):
        return provider._create_image_result(
            "File:Huette.jpg", _image_result_data(**overrides), None, 50, 46.5, 7.5
        )

    def test_medium_is_thumb_bucket(self, provider):
        result = self._create(provider)
        assert result.url_medium == THUMB_500_URL

    def test_large_is_thumb_capped_at_3000(self, provider):
        result = self._create(provider)  # original 4000px wide
        assert result.url_large == _wikimedia_thumb_url(THUMB_500_URL, 3000)
        assert result.url_large.endswith("3000px-Huette.jpg")

    def test_large_is_full_width_below_cap(self, provider):
        result = self._create(provider, width=2500)
        assert result.url_large.endswith("2500px-Huette.jpg")

    def test_tiff_is_capped_at_1920(self, provider):
        result = self._create(provider, mime="image/tiff")
        assert result.url_large.endswith("1920px-Huette.jpg")

    def test_tiff_below_cap_uses_own_width(self, provider):
        result = self._create(provider, mime="image/tiff", width=1700)
        assert result.url_large.endswith("1700px-Huette.jpg")

    def test_small_original_served_directly(self, provider):
        """Originals not larger than the medium bucket stay the original URL."""
        result = self._create(provider, width=480)
        assert result.url_large == ORIGINAL_URL
        assert result.url_medium == ORIGINAL_URL

    def test_dimensions_stay_true_original(self, provider):
        result = self._create(provider)
        assert (result.width, result.height) == (4000, 3000)

    def test_original_url_preserved_in_extra(self, provider):
        result = self._create(provider)
        assert result.extra["original_url"] == ORIGINAL_URL


def _image_result_data(**overrides) -> dict:
    return _img_data(**overrides)


def _quoted(url: str) -> str:
    return quote(url, safe="")


@pytest.fixture
def patched_lookups(monkeypatch):
    """Keep post-processing off the database (pure URL-mapping assertions)."""
    monkeypatch.setattr(providers_base, "_get_provider_info", lambda *a, **k: {})
    monkeypatch.setattr(providers_base, "_get_license_info", lambda *a, **k: {})


class TestPostProcessSourceSelection:
    def test_small_variants_use_medium_source(self, patched_lookups):
        result = _image_result(url_medium=THUMB_500_URL)
        [feature] = post_process_images([result])
        urls = feature["properties"]["urls"]

        for variant in (
            urls["square"]["avatar"],
            urls["square"]["thumb@2x"],
            urls["landscape"]["preview"],
            urls["portrait"]["thumb"],
        ):
            assert _quoted(THUMB_500_URL) in variant

    def test_large_variants_use_large_source(self, patched_lookups):
        result = _image_result(url_medium=THUMB_500_URL)
        [feature] = post_process_images([result])
        urls = feature["properties"]["urls"]

        for variant in (
            urls["square"]["medium"],
            urls["landscape"]["large"],
            urls["portrait"]["preview@2x"],
            urls["original"]["proxy"],
        ):
            assert _quoted(ORIGINAL_URL) in variant

    def test_original_raw_is_large_source_not_true_original(self, patched_lookups):
        """For Wikimedia the provider already points url_large at a thumb."""
        thumb_3000 = _wikimedia_thumb_url(THUMB_500_URL, 3000)
        result = _image_result(url_large=thumb_3000, url_medium=THUMB_500_URL)
        [feature] = post_process_images([result])
        original = feature["properties"]["urls"]["original"]
        assert original["raw"] == thumb_3000
        assert _quoted(thumb_3000) in original["proxy"]

    def test_without_url_medium_all_variants_use_large(self, patched_lookups):
        """Providers that do not set url_medium keep their previous URLs."""
        result = _image_result()
        [feature] = post_process_images([result])
        urls = feature["properties"]["urls"]

        # Golden pair: square thumb and landscape large must embed the
        # (single) source URL exactly as the old always-url_large behavior did.
        assert _quoted(ORIGINAL_URL) in urls["square"]["thumb"]
        assert _quoted(ORIGINAL_URL) in urls["landscape"]["large"]
        # No variant may fall back to an empty or different source.
        for orientation in ("square", "landscape", "portrait"):
            for name, variant in urls[orientation].items():
                assert _quoted(ORIGINAL_URL) in variant, (orientation, name)

    def test_threshold_is_constrained_target(self, patched_lookups):
        """500px max dimension is the cut: preview@2x (800px) leaves medium."""
        result = _image_result(url_medium=THUMB_500_URL)
        [feature] = post_process_images([result])
        urls = feature["properties"]["urls"]

        assert _quoted(THUMB_500_URL) in urls["square"]["preview"]  # 400
        assert _quoted(ORIGINAL_URL) in urls["square"]["preview@2x"]  # 800


class TestConstrainedSize:
    def test_square_constrained_by_portrait_original(self):
        assert _calculate_constrained_size(400, 400, 500, 333) == (333, 333)

    def test_unconstrained_when_target_fits(self):
        assert _calculate_constrained_size(400, 267, 4000, 3000) == (400, 267)

    def test_threshold_constant(self):
        assert MEDIUM_SOURCE_MAX_DIMENSION == WIKIMEDIA_MEDIUM_THUMB_WIDTH == 500
        assert WIKIMEDIA_THUMB_MAX_WIDTH == 3000
        assert WIKIMEDIA_TIFF_THUMB_MAX_WIDTH == 1920
