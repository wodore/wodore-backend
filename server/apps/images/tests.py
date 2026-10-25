"""Tests for the image assessment pipeline.

Focus: ``assess_place_pins`` must survive images whose ``image_meta``
carries no width — pinned SVGs (e.g. camptocamp vector logos) have no
intrinsic raster dimensions. Regression for the Sentry issue
``TypeError: bad operand type for unary -: 'NoneType'`` (155854824):
the sort key ``-(meta.get("width") or 0)`` parsed as
``(-meta.get("width")) or 0`` and crashed on ``None`` before the
``or 0`` fallback could apply.
"""

from __future__ import annotations

import pytest

from django.contrib.gis.geos import Point

from server.apps.categories.models import Category
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.assessment import assess_place_pins
from server.apps.images.models import Image
from server.apps.licenses.models import License


def _image(
    license: License, *, phash: str, quality: int, meta: dict[str, int] | None
) -> Image:
    return Image.objects.create(
        license=license,
        phash=phash,
        quality_score=quality,
        image_meta=meta,
        source_ident=f"c2c:{phash}",
    )


@pytest.fixture
def hut():
    parent = Category.objects.create(slug="accommodation")
    hut_type = Category.objects.create(slug="alpinehut-open", parent=parent, order=1)
    return Hut.objects.create(
        slug="regression-hut",
        name="Regression Hut",
        location=Point(9.0, 46.0, srid=4326),
        is_active=True,
        is_public=True,
        country_field="CH",
        hut_type_open=hut_type,
    )


@pytest.mark.django_db
class TestAssessPlacePins:
    """Duplicate clustering across pins — sort-key robustness."""

    def test_images_without_width_do_not_crash(self, hut: Hut) -> None:
        """Pinned SVGs (no meta width) must sort, not raise TypeError."""
        license = License.objects.create(slug="cc-by-sa-4.0")
        raster = _image(
            license,
            phash="0" * 16,
            quality=50,
            # Raster pin: meta carries the usual width/height.
            meta={"provider_score": 80, "width": 1600, "height": 1067},
        )
        svg = _image(
            license,
            phash="f" * 16,
            quality=40,
            # SVG pin: provider score only — no width at all (the exact
            # shape of the crash in Sentry 155854824).
            meta={"provider_score": 70},
        )
        svg_no_meta = _image(
            license,
            phash="5" * 16,
            quality=30,
            meta=None,
        )
        for image in (raster, svg, svg_no_meta):
            HutImageAssociation.objects.create(hut=hut, image=image, score=50)

        # Pre-fix: TypeError — unary minus applied to None before `or 0`.
        stats = assess_place_pins(hut)

        assert stats == {"assessed": 0, "duplicates": 0, "pins": 3}

    def test_duplicate_cluster_prefers_higher_quality(self, hut: Hut) -> None:
        """Equal phash → cluster; quality score picks the primary."""
        license = License.objects.create(slug="cc-by-sa-4.0")
        strong = _image(
            license,
            phash="ab" * 8,
            quality=90,
            meta={"width": 2000},
        )
        weak = _image(
            license,
            phash="ab" * 8,  # identical hash → hamming distance 0
            quality=20,
            # No width: tiebreak must fall back to 0, not crash.
            meta={"provider_score": 10},
        )
        HutImageAssociation.objects.create(hut=hut, image=strong, score=90)
        HutImageAssociation.objects.create(hut=hut, image=weak, score=20)

        stats = assess_place_pins(hut)

        assert stats["duplicates"] == 1
        weak.refresh_from_db()
        assert weak.image_meta["duplicate_of"] == strong.source_ident  # type: ignore  # optional config access in test
