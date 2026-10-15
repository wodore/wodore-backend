"""Tests for image display in the huts admin (Photos tab) and Image model tags.

Regression: the Photos tab called ``img.image.url`` — pinned external images
have no local file, so that raised ValueError and 500'd the whole hut change
page. Thumbnails likewise rendered "Missing" for every pin.
"""

import pytest

from django.contrib import admin as django_admin

from server.apps.huts.admin._hut import HutsAdmin
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def hut(seed_data):
    hut = Hut.objects.filter(is_active=True, is_public=True).first()
    assert hut is not None
    HutImageAssociation.objects.filter(hut=hut).delete()
    return hut


def _pin(hut: Hut, ident: str, score: int = 50) -> Image:
    slug = ident.split(":")[0]
    license_obj, _created = License.objects.get_or_create(
        slug="cc-by-sa-4-0",
        defaults={"name": "cc", "fullname": "cc", "no_publication": False},
    )
    org, _created = Organization.objects.get_or_create(
        slug=slug, defaults={"name_en": slug}
    )
    image = Image.objects.create(
        source_ident=ident,
        license=license_obj,
        source_org=org,
        source_url=f"https://example.org/{ident}",
        source_url_raw=f"https://example.org/{ident}.jpg",
        caption_en=ident,
    )
    HutImageAssociation.objects.create(image=image, hut=hut, score=score)
    return image


@pytest.fixture
def admin() -> HutsAdmin:
    return HutsAdmin(Hut, django_admin.site)


class TestGetImageTag:
    def test_pin_falls_back_to_raw_url(self):
        image = Image(
            source_url_raw="https://example.org/photo.jpg",
            image_meta={"width": 2000, "height": 1000},
        )
        html = str(image.get_image_tag())
        assert "<img" in html
        assert "Missing" not in html

    def test_local_file_still_used(self):
        image = Image(
            image="images/huts/x/photo.jpg",
            image_meta={"width": 2000, "height": 1000},
        )
        html = str(image.get_image_tag())
        assert "<img" in html
        assert "Missing" not in html


class TestHutImagesTab:
    def test_renders_pinned_hut_without_error(self, admin, hut):
        _pin(hut, "camptocamp:waypoint_1_a.jpg")
        _pin(hut, "wikicommons:File:Test.jpg", score=40)
        html = str(admin.hut_images(hut))
        assert "<img" in html
        assert "Missing" not in html
        # View link points at the raw source URL (not img.image.url, which
        # raises for pins).
        assert "https://example.org/camptocamp:waypoint_1_a.jpg" in html
        # Edit links to the image admin.
        assert "admin:images_image_change" not in html  # reversed URL, not literal
        assert "/admin/images/image/" in html

    def test_caps_listing_with_more_note(self, admin, hut):
        for i in range(35):
            _pin(hut, f"camptocamp:photo_{i}.jpg", score=89 - (i % 89))
        html = str(admin.hut_images(hut))
        assert "and 5 more" in html
        assert "details__hut" in html  # deep link into the image changelist

    def test_empty_hut_renders_empty_div(self, admin, hut):
        assert str(admin.hut_images(hut)) == "<div></div>"
