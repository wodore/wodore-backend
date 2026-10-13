"""Tests for the geoimages_dedupe_pins management command.

Removes prefix-stacked duplicate pins ("camptocamp:camptocamp:...") minted by
the historical re-pinning bug (see test_image_pinning.py) — dry run by
default, deletion + response-cache invalidation with --apply.
"""

import io

import pytest

from django.core.management import call_command

from server.apps.geometries import image_response_cache as irc_geo
from server.apps.huts.models import Hut, HutImageAssociation
from server.apps.images.models import Image
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch):
    """Private locmem response cache per test (no database cache leakage)."""
    from uuid import uuid4

    from django.core.cache.backends.locmem import LocMemCache

    cache = LocMemCache(f"test-{uuid4().hex}", {})
    monkeypatch.setattr(irc_geo, "_cache", lambda: cache)


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


def _run(*args: str) -> str:
    out = io.StringIO()
    call_command("geoimages_dedupe_pins", *args, stdout=out)
    return out.getvalue()


class TestDedupePinsCommand:
    def test_no_duplicates(self, hut):
        _pin(hut, "camptocamp:waypoint_1_a.jpg")
        _pin(hut, "wikicommons:File:Test.jpg")
        assert "No duplicated pins found." in _run()

    def test_dry_run_reports_without_deleting(self, hut):
        _pin(hut, "camptocamp:waypoint_1_a.jpg")
        duplicate = _pin(hut, "camptocamp:camptocamp:waypoint_1_a.jpg")
        output = _run()
        assert "1 duplicated image(s)" in output
        assert "Dry run" in output
        assert Image.objects.filter(pk=duplicate.pk).exists()

    def test_apply_deletes_only_duplicates(self, hut):
        keep = _pin(hut, "camptocamp:waypoint_1_a.jpg")
        control = _pin(hut, "wikicommons:File:Test.jpg")
        duplicate = _pin(hut, "camptocamp:camptocamp:waypoint_1_a.jpg")
        output = _run("--apply")
        assert not Image.objects.filter(pk=duplicate.pk).exists()
        assert Image.objects.filter(pk__in=[keep.pk, control.pk]).count() == 2
        assert HutImageAssociation.objects.filter(hut=hut).count() == 2
        assert "Deleted 1 duplicate image(s)" in output

    def test_apply_invalidates_place_cache(self, hut):
        _pin(hut, "camptocamp:waypoint_1_a.jpg")
        _pin(hut, "camptocamp:camptocamp:waypoint_1_a.jpg")
        version_before = irc_geo.get_version("hut", hut.slug)
        _run("--apply")
        assert irc_geo.get_version("hut", hut.slug) > version_before

    def test_place_filter_scopes_deletion(self, hut):
        from server.apps.huts.models import Hut as HutModel

        other = (
            HutModel.objects.filter(is_active=True, is_public=True)
            .exclude(pk=hut.pk)
            .first()
        )
        if other is None:
            pytest.skip("seed data carries a single hut")
        HutImageAssociation.objects.filter(hut=other).delete()
        duplicate = _pin(hut, "camptocamp:camptocamp:waypoint_1_a.jpg")
        other_duplicate = _pin(other, "camptocamp:camptocamp:waypoint_9_z.jpg")
        output = _run("--place", hut.slug, "--apply")
        assert not Image.objects.filter(pk=duplicate.pk).exists()
        assert Image.objects.filter(pk=other_duplicate.pk).exists()
        assert "Deleted 1 duplicate image(s)" in output

    def test_triple_prefixes_also_detected(self, hut):
        _pin(hut, "wikicommons:wikicommons:wikicommons:File:X.jpg")
        output = _run()
        assert "1 duplicated image(s)" in output
