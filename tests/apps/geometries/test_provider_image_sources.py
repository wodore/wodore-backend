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
    WIKIMEDIA_LARGE_THUMB_WIDTH,
    WIKIMEDIA_MEDIUM_THUMB_WIDTH,
    WikimediaCommonsProvider,
)

ORIGINAL_URL = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Huette.jpg"
THUMB_500_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/"
    "Huette.jpg/500px-Huette.jpg"
)
THUMB_1920_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/"
    "Huette.jpg/1920px-Huette.jpg"
)


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
        thumb_url_large=THUMB_1920_URL,
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

    def test_large_uses_large_bucket_thumb(self, provider):
        """url_large comes from the dedicated iiurlwidth=1920 API pass.

        Wikimedia serves thumbs only at listed sizes; hand-rewritten
        widths (the old approach) answer 400.
        """
        result = self._create(provider)  # original 4000px wide
        assert result.url_large == THUMB_1920_URL

    def test_large_falls_back_to_medium_when_large_pass_missing(self, provider):
        result = self._create(provider, thumb_url_large="")
        assert result.url_large == THUMB_500_URL

    def test_large_falls_back_to_original_without_thumbs(self, provider):
        result = self._create(provider, thumb_url_large="", thumb_url="")
        assert result.url_large == ORIGINAL_URL
        assert result.url_medium == ORIGINAL_URL

    def test_tiff_large_uses_api_thumb(self, provider):
        """TIFF needs no special casing: the API returns a pre-rendered
        JPEG thumb for the large bucket."""
        result = self._create(provider, mime="image/tiff")
        assert result.url_large == THUMB_1920_URL

    def test_small_original_served_directly(self, provider):
        """Originals not larger than the buckets: the API returns the
        original URL as thumburl in both passes — served directly."""
        result = self._create(
            provider, width=480, thumb_url=ORIGINAL_URL, thumb_url_large=ORIGINAL_URL
        )
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

    def test_constrained_not_nominal_size_selects_source(self, patched_lookups):
        """Discriminator: selection must use the CONSTRAINED target size.

        Square "medium" is nominally 1000x1000 (> 500 → large source under a
        nominal-only implementation), but against an 800x460 original it is
        constrained to 460x460 (<= 500) and must pick the medium source.
        """
        result = _image_result(url_medium=THUMB_500_URL, width=800, height=460)
        [feature] = post_process_images([result])
        urls = feature["properties"]["urls"]

        assert _calculate_constrained_size(1000, 1000, 800, 460) == (460, 460)
        assert _quoted(THUMB_500_URL) in urls["square"]["medium"]

    def test_original_raw_is_large_source_not_true_original(self, patched_lookups):
        """For Wikimedia the provider already points url_large at a thumb."""
        result = _image_result(url_large=THUMB_1920_URL, url_medium=THUMB_500_URL)
        [feature] = post_process_images([result])
        original = feature["properties"]["urls"]["original"]
        assert original["raw"] == THUMB_1920_URL
        assert _quoted(THUMB_1920_URL) in original["proxy"]

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
        assert WIKIMEDIA_LARGE_THUMB_WIDTH == 1920
