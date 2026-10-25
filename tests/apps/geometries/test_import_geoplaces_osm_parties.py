"""Tests for the OSM import's party minting (task 2.3, review finding 2).

Covers both precache paths without network access: single brand tag →
role.brand party, single-value operator tag → role.operator party
minted into review, multi-value tags skipped, and idempotent re-runs.
"""

from io import StringIO
from typing import Any

import pytest

from django.core.management.base import OutputWrapper

from server.apps.geometries.management.commands.geoplaces_import_osm import Command
from server.apps.parties.models import Party

pytestmark = pytest.mark.django_db


def _command() -> Command:
    cmd = Command()
    cmd.stdout = OutputWrapper(StringIO())
    return cmd


def _amenity(**tags: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"category_slug": "amenity.restaurant"}
    data.update(tags)
    return data


class TestPrecacheDataParties:
    def test_brand_tag_mints_brand_party(self):
        _command()._precache_data([_amenity(brand="Volg")])

        party = Party.objects.get(slug="volg")
        assert party.name == "Volg"
        assert party.review_status == "done"

    def test_single_operator_tag_mints_into_review(self):
        _command()._precache_data([_amenity(operator="SAC Bern")])

        party = Party.objects.get(slug="sac_bern")
        assert party.name == "SAC Bern"
        assert party.review_status == "review"

    def test_multi_value_tags_skipped(self):
        before = set(Party.objects.values_list("slug", flat=True))

        _command()._precache_data([_amenity(brand="A; B", operator="C; D")])

        assert set(Party.objects.values_list("slug", flat=True)) == before

    def test_idempotent_rerun(self):
        cmd = _command()
        cmd._precache_data([_amenity(brand="Volg")])
        cmd._precache_data([_amenity(brand="Volg")])

        assert Party.objects.filter(slug="volg").count() == 1


class TestPrecacheMappingDataParties:
    def test_operator_minting_on_mapping_path(self):
        _command()._precache_mapping_data([_amenity(brand="Volg", operator="SAC Bern")])

        assert Party.objects.get(slug="volg").review_status == "done"
        assert Party.objects.get(slug="sac_bern").review_status == "review"

    def test_idempotent_rerun(self):
        cmd = _command()
        cmd._precache_mapping_data([_amenity(brand="Volg")])
        cmd._precache_mapping_data([_amenity(brand="Volg")])

        assert Party.objects.filter(slug="volg").count() == 1
