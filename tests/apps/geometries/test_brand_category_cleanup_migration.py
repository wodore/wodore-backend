"""geometries 0055 brand-category cleanup migration tests.

Seeds a legacy ``root.brand`` subtree with a place association (the
RESTRICT blocker the migration must clear first), runs
``remove_brand_categories`` against the live registry, and asserts:
subtree gone, legacy associations gone, ``role.*`` vocabulary and
party associations untouched, re-run is a no-op.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.parties import PartyFactory

from server.apps.categories.models import Category
from server.apps.geometries.models import GeoPlaceCategory, GeoPlaceParty

pytestmark = pytest.mark.django_db

MIGRATION = "server.apps.geometries.migrations.0056_remove_brand_categories"


def _migration() -> Any:
    return importlib.import_module(MIGRATION)


class _RealApps:
    def get_model(self, app_label: str, model_name: str) -> Any:
        from django.apps import apps

        return apps.get_model(app_label, model_name)


def _seed_brand_tree() -> Category:
    root = Category.objects.create(slug="brand", name="Brand")
    Category.objects.create(slug="volg", parent=root, name="Volg")
    Category.objects.create(slug="coop", parent=root, name="Coop")
    return root


def _role(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="role")


class TestRemoveBrandCategories:
    def test_removes_subtree_and_legacy_associations(self):
        root = _seed_brand_tree()
        volg = Category.objects.get(slug="volg", parent=root)
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(geo_place=place, category=volg)

        _migration().remove_brand_categories(_RealApps(), None)

        assert not Category.objects.filter(identifier="root.brand").exists()
        assert not Category.objects.filter(slug__in=["volg", "coop"]).exists()
        assert not GeoPlaceCategory.objects.filter(category__slug="volg").exists()

    def test_role_vocabulary_and_parties_survive(self):
        _seed_brand_tree()
        place = GeoPlaceFactory()
        party = PartyFactory(name="Volg")
        role_brand = _role("brand")
        association = GeoPlaceParty.objects.create(
            geo_place=place, party=party, role=role_brand
        )

        _migration().remove_brand_categories(_RealApps(), None)

        # role.* is a different vocabulary entirely — untouched.
        assert Category.objects.filter(identifier="role.brand").exists()
        assert Category.objects.filter(identifier="root.role").exists()
        # The party association written by the 0053 conversion stays.
        assert GeoPlaceParty.objects.filter(pk=association.pk).exists()

    def test_association_to_root_itself_cleared(self):
        root = _seed_brand_tree()
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(geo_place=place, category=root)

        _migration().remove_brand_categories(_RealApps(), None)

        assert not GeoPlaceCategory.objects.filter(category=root.pk).exists()

    def test_rerun_is_noop(self):
        _seed_brand_tree()

        _migration().remove_brand_categories(_RealApps(), None)
        _migration().remove_brand_categories(_RealApps(), None)  # idempotent

        assert not Category.objects.filter(identifier="root.brand").exists()

    def test_unrelated_categories_survive(self):
        _seed_brand_tree()
        other = Category.objects.create(slug="other-vocab", name="Other")
        Category.objects.create(slug="other-child", parent=other)

        _migration().remove_brand_categories(_RealApps(), None)

        assert Category.objects.filter(identifier="root.other-vocab").exists()
        assert Category.objects.filter(identifier="other-vocab.other-child").exists()
