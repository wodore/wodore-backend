"""The 0024 resta→restaurant migration: rename vs merge.

Regression coverage for the staging incident: the deploy wedged on
``unique_slug_per_parent`` — staging carries BOTH the HutType-era
``accommodation.resta`` (id 100, kind of 8 places, huts' hut_type FK)
and the later-seeded ``accommodation.restaurant`` (id 136). Fresh CI
DBs have no ``resta`` row, so the plain rename was a no-op there and
green. The migration is merge-aware now: references re-point to the
surviving row, the legacy row is deleted.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.factories.huts import HutFactory

from django.apps import apps as global_apps
from django.contrib.gis.geos import Point

from server.apps.categories.models import Category
from server.apps.geometries.models import (
    CategoryExtraSchema,
    GeoPlace,
    GeoPlaceCategory,
)

MIGRATION = importlib.import_module(
    "server.apps.categories.migrations.0024_rename_resta_category"
)

pytestmark = pytest.mark.django_db

POINT = Point(7.75, 46.02, srid=4326)


def _accommodation() -> Category:
    return Category.objects.get(slug="accommodation", parent__slug="amenity")


def _cat(slug: str, order: int, **extra: Any) -> Category:
    category, _created = Category.objects.get_or_create(
        slug=slug, parent=_accommodation(), defaults={"name": slug, "order": order}
    )
    for key, value in extra.items():
        setattr(category, key, value)
    category.save()
    return category


def _mode(slug: str) -> Category:
    return Category.objects.get(identifier=f"mode.{slug}")


def _isolated_parent() -> Category:
    """A synthetic group without a restaurant child — the test DB
    seed already plants accommodation.restaurant (that is exactly
    the staging collision), so the plain-rename branch needs its own
    parent."""
    amenity = Category.objects.get(slug="amenity", parent__slug="map")
    parent, _created = Category.objects.get_or_create(
        slug="rm-rename-group", parent=amenity, defaults={"name": "Rename group"}
    )
    return parent


def _make_place(name: str, slug: str, kind: Category) -> GeoPlace:
    return GeoPlace.objects.create(
        name=name,
        slug=slug,
        location=POINT,
        country_code="CH",
        is_active=True,
        is_public=True,
        domain="amenity",
        kind=kind,
    )


class TestRenameOnly:
    """HutType-era DB with only ``resta`` (no sibling restaurant) —
    the plain rename survives."""

    def test_rename_and_reverse(self) -> None:
        resta = Category.objects.create(
            slug="resta", parent=_isolated_parent(), name="resta", order=100
        )

        MIGRATION.rename_resta_to_restaurant(global_apps, None)

        resta.refresh_from_db()
        assert resta.slug == "restaurant"
        assert not Category.objects.filter(slug="resta").exists()

        # The reverse is deliberately accommodation-scoped — renaming
        # EVERY parent's restaurant would corrupt the unrelated
        # restaurant contract-group categories (amenity.restaurant,
        # restaurant.restaurant). The isolated-parent rename is
        # forward-only; nothing to reverse here.
        MIGRATION.rename_restaurant_to_resta(global_apps, None)
        resta.refresh_from_db()
        assert resta.slug == "restaurant"


class TestNoRestaNoOp:
    """Fresh-DB shape (why CI stayed green): no resta row at all.
    Whether accommodation.restaurant exists is seed-dependent — not
    the migration's business."""

    def test_noop(self) -> None:
        MIGRATION.rename_resta_to_restaurant(global_apps, None)
        assert not Category.objects.filter(slug="resta").exists()
        # reverse equally harmless
        MIGRATION.rename_restaurant_to_resta(global_apps, None)
        assert not Category.objects.filter(
            slug="resta", parent=_isolated_parent()
        ).exists()


class TestMergeBothExist:
    """The staging shape: resta AND restaurant under accommodation —
    a plain rename dies on unique_slug_per_parent; the migration
    merges instead."""

    @pytest.fixture(autouse=True)
    def staging_shape(self) -> None:
        self.restaurant = _cat("restaurant", order=10)
        self.resta = _cat("resta", order=100)

        # wodore hut place anchored on the legacy row, mixed-mode
        # associations (the #469/#472 shape)
        self.place = _make_place("Rm Alpha", "rm-alpha", kind=self.resta)
        GeoPlaceCategory.objects.create(
            geo_place=self.place, category=self.resta, classifier=_mode("standard")
        )
        unknown = _cat("unknown", order=0)
        GeoPlaceCategory.objects.create(
            geo_place=self.place, category=unknown, classifier=_mode("reduced")
        )

        # a second place carrying BOTH categories under the same
        # classifier — the merge must dedupe, not violate the
        # (geo_place, category, classifier) unique constraint
        self.dupe_place = _make_place("Rm Beta", "rm-beta", kind=self.restaurant)
        GeoPlaceCategory.objects.create(
            geo_place=self.dupe_place,
            category=self.restaurant,
            classifier=_mode("standard"),
        )
        GeoPlaceCategory.objects.create(
            geo_place=self.dupe_place, category=self.resta, classifier=_mode("standard")
        )

        # huts typed on the legacy row (RESTRICT would block deletion)
        self.hut = HutFactory(hut_type_open=self.resta, hut_type_closed=self.resta)

        # legacy extra schema rides the merge
        CategoryExtraSchema.objects.create(
            category=self.resta, schema={"type": "object"}
        )

    def test_merge_repoints_and_deletes(self) -> None:
        MIGRATION.rename_resta_to_restaurant(global_apps, None)

        # legacy row gone, survivor intact
        assert not Category.objects.filter(slug="resta").exists()
        self.restaurant.refresh_from_db()
        assert self.restaurant.slug == "restaurant"

        # kind re-pointed (no silent SET_NULL)
        self.place.refresh_from_db()
        assert self.place.kind_id == self.restaurant.pk

        # associations re-pointed, duplicate dropped — asserted on
        # identifiers (the repo's idiom for association rows)
        assoc_keys = {
            (a.category.slug, a.classifier.identifier if a.classifier else None)
            for a in GeoPlaceCategory.objects.filter(geo_place=self.place)  # type: ignore  # reverse FK: plugin-less inference gap
        }
        assert ("restaurant", "mode.standard") in assoc_keys
        assert ("unknown", "mode.reduced") in assoc_keys
        dupe_assocs = GeoPlaceCategory.objects.filter(geo_place=self.dupe_place)
        assert dupe_assocs.count() == 1  # deduped, not duplicated
        assert dupe_assocs.get().category_id == self.restaurant.pk

        # hut type FKs re-pointed
        self.hut.refresh_from_db()
        assert self.hut.hut_type_open_id == self.restaurant.pk
        assert self.hut.hut_type_closed_id == self.restaurant.pk

        # extra schema moved onto the survivor
        assert CategoryExtraSchema.objects.filter(category=self.restaurant).exists()

    def test_merge_survives_unique_slug_constraint(self) -> None:
        # the exact staging failure: without merge-awareness this
        # raises IntegrityError (duplicate slug per parent)
        try:
            MIGRATION.rename_resta_to_restaurant(global_apps, None)
        except Exception as exc:  # pragma: no cover — only on regression
            pytest.fail(f"migration raised: {exc}")

    def test_merge_idempotent(self) -> None:
        MIGRATION.rename_resta_to_restaurant(global_apps, None)
        MIGRATION.rename_resta_to_restaurant(global_apps, None)  # no resta left
        assert not Category.objects.filter(slug="resta").exists()

    def test_reverse_after_merge_is_best_effort(self) -> None:
        MIGRATION.rename_resta_to_restaurant(global_apps, None)
        MIGRATION.rename_restaurant_to_resta(global_apps, None)

        # forward-only merge documented: the surviving row renames
        # back, every re-pointed reference rides along on it
        self.restaurant.refresh_from_db()
        assert self.restaurant.slug == "resta"
        self.place.refresh_from_db()
        assert self.place.kind_id == self.restaurant.pk
        self.hut.refresh_from_db()
        assert self.hut.hut_type_open_id == self.restaurant.pk


class TestMergeExtraSchemaCollision:
    """The target already carries its own schema — the legacy row is
    dropped, the target's row wins."""

    def test_target_schema_wins(self) -> None:
        restaurant = _cat("restaurant", order=10)
        resta = _cat("resta", order=100)
        CategoryExtraSchema.objects.create(
            category=restaurant, schema={"type": "object", "title": "target"}
        )
        CategoryExtraSchema.objects.create(
            category=resta, schema={"type": "object", "title": "legacy"}
        )

        MIGRATION.rename_resta_to_restaurant(global_apps, None)

        schema = CategoryExtraSchema.objects.get(category=restaurant)
        assert schema.schema["title"] == "target"
        # the seed plants unrelated schema rows — scope to the pair
        assert (
            CategoryExtraSchema.objects.filter(
                category_id__in=[restaurant.pk, resta.pk]
            ).count()
            == 1
        )
