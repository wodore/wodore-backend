"""Unit tests for GeoPlaceParty associations and the role vocabulary.

OpenSpec change: ``geoplace-parties`` (tasks 1.1 and 1.3) — the
vocabulary is seeded by migration ``0052`` (runs on the test database),
so these tests pin the seed and the association contract: role-subtree
validation, uniqueness per ``(geo_place, party, role)``, separate rows
for multiple roles, and RESTRICT on party and role FKs.
"""

import pytest

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.parties import PartyFactory

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlaceParty

pytestmark = pytest.mark.django_db


def role(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="role")


class TestRoleVocabulary:
    def test_vocabulary_seeded_by_migration(self):
        parent = Category.objects.get(slug="role", parent__isnull=True)
        assert parent.is_active
        assert parent.name  # German source name seeded

        children = list(
            parent.children.order_by("order").values_list("slug", flat=True)
        )
        assert children == ["operator", "brand", "owner", "source"]

        # The computed ``identifier`` column must be populated — data
        # migrations create rows through historical models, so
        # computedfields never fires (see categories' 0006 precedent).
        assert parent.identifier == "root.role"
        for child in parent.children.all():
            assert child.identifier == f"role.{child.slug}"
            assert child.is_active
            assert child.name
            assert child.i18n.get("name_en")  # English translation seeded


class TestGeoPlaceParty:
    def test_valid_association_passes_clean(self):
        place = GeoPlaceFactory()
        party = PartyFactory()

        association = GeoPlaceParty(geo_place=place, party=party, role=role("operator"))
        association.full_clean()
        association.save()

        assert place.party_associations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap
        assert place.party_associations.first().role.slug == "operator"  # type: ignore  # reverse FK

    def test_multiple_roles_are_separate_rows(self):
        place = GeoPlaceFactory()
        party = PartyFactory()

        GeoPlaceParty.objects.create(geo_place=place, party=party, role=role("brand"))
        GeoPlaceParty.objects.create(
            geo_place=place, party=party, role=role("operator")
        )

        assert place.party_associations.count() == 2  # type: ignore  # reverse FK: plugin-less inference gap

    def test_duplicate_place_party_role_rejected(self):
        place = GeoPlaceFactory()
        party = PartyFactory()
        GeoPlaceParty.objects.create(geo_place=place, party=party, role=role("owner"))

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceParty.objects.create(
                    geo_place=place, party=party, role=role("owner")
                )

    def test_clean_rejects_role_parent_itself(self):
        parent = Category.objects.get(slug="role", parent__isnull=True)
        association = GeoPlaceParty(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=parent
        )

        with pytest.raises(ValidationError):
            association.clean()

    def test_clean_rejects_child_of_other_subtree(self):
        other_parent = Category.objects.create(slug="other-vocab")
        other_child = Category.objects.create(slug="other-child", parent=other_parent)
        association = GeoPlaceParty(
            geo_place=GeoPlaceFactory(),
            party=PartyFactory(),
            role=other_child,
        )

        with pytest.raises(ValidationError):
            association.clean()

    def test_party_delete_restricted_while_in_use(self):
        association = GeoPlaceParty.objects.create(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=role("brand")
        )

        with pytest.raises(RestrictedError):
            association.party.delete()

    def test_role_delete_restricted_while_in_use(self):
        association = GeoPlaceParty.objects.create(
            geo_place=GeoPlaceFactory(), party=PartyFactory(), role=role("brand")
        )

        with pytest.raises(RestrictedError):
            association.role.delete()
