"""Tests for the 0066 score-rebanding data migration.

Uploads lived at 1000+ (breaking the image endpoints' 0–100 response
contract); bands move to uploads 90–99 (newest import first) and pins ≤ 89.
"""

import importlib

import pytest

from server.apps.geometries.models import GeoPlaceImageAssociation
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db

migration = importlib.import_module(
    "server.apps.huts.migrations.0066_reband_image_association_scores"
)


class _StubApps:
    """Historical-apps stand-in returning the real (post-migrate) models."""

    @staticmethod
    def get_model(app_label: str, model_name: str):
        return {
            ("huts", "HutImageAssociation"): HutImageAssociation,
            ("geometries", "GeoPlaceImageAssociation"): GeoPlaceImageAssociation,
        }[(app_label, model_name)]


@pytest.fixture
def hut(seed_data: dict[str, int]):
    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    return hut


def _image(ident: str) -> Image:
    license_obj, _created = License.objects.get_or_create(
        slug="cc-by-sa-4-0",
        defaults={"name": "cc", "fullname": "cc", "no_publication": False},
    )
    org, _created = Organization.objects.get_or_create(
        slug=ident.split(":")[0], defaults={"name_en": ident.split(":")[0]}
    )
    return Image.objects.create(source_ident=ident, license=license_obj, source_org=org)


def _scores(hut: Hut) -> list[int]:
    return list(
        HutImageAssociation.objects.filter(hut=hut)
        .order_by("image__source_ident")
        .values_list("score", flat=True)
    )


class TestRemapScores:
    def test_uploads_rebanded_newest_first(self, hut: Hut):
        oldest = _image("a:old.jpg")
        newest = _image("a:new.jpg")
        HutImageAssociation.objects.create(image=oldest, hut=hut, score=1000)
        HutImageAssociation.objects.create(image=newest, hut=hut, score=1001)
        migration.remap_scores(_StubApps(), None)
        by_ident = dict(
            HutImageAssociation.objects.filter(hut=hut).values_list(
                "image__source_ident", "score"
            )
        )
        assert by_ident["a:new.jpg"] == 99  # newest import first
        assert by_ident["a:old.jpg"] == 98

    def test_uploads_stack_caps_at_90(self, hut: Hut):
        for i in range(14):
            HutImageAssociation.objects.create(
                image=_image(f"a:img_{i:02}.jpg"), hut=hut, score=1000 + i
            )
        migration.remap_scores(_StubApps(), None)
        scores = sorted(
            HutImageAssociation.objects.filter(hut=hut).values_list("score", flat=True)
        )
        # 14 uploads squeeze into the 90..99 band (oldest share the floor).
        assert scores == [90] * 5 + [91, 92, 93, 94, 95, 96, 97, 98, 99]

    def test_gap_scores_clamped_to_pin_band(self, hut: Hut):
        image = _image("camptocamp:strong.jpg")
        HutImageAssociation.objects.create(image=image, hut=hut, score=95)
        migration.remap_scores(_StubApps(), None)
        assert HutImageAssociation.objects.get(image=image, hut=hut).score == 89

    def test_pins_below_90_untouched(self, hut: Hut):
        image = _image("camptocamp:weak.jpg")
        HutImageAssociation.objects.create(image=image, hut=hut, score=50)
        migration.remap_scores(_StubApps(), None)
        assert HutImageAssociation.objects.get(image=image, hut=hut).score == 50

    def test_geoplace_associations_rebanded_too(self):
        from tests.factories.geometries import GeoPlaceFactory

        place = GeoPlaceFactory(slug="reband-place")
        image = _image("camptocamp:geo.jpg")
        GeoPlaceImageAssociation.objects.create(
            image=image, geo_place=place, score=1200
        )
        migration.remap_scores(_StubApps(), None)
        assert GeoPlaceImageAssociation.objects.get(image=image).score == 99
