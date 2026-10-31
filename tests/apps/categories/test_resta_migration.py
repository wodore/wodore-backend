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
from datetime import date
from typing import Any

import pytest

from tests.factories.huts import HutFactory

from django.apps import apps as global_apps
from django.contrib.gis.geos import Point
from django.utils import timezone

from server.apps.availability.models import HutAvailability, HutAvailabilityHistory
from server.apps.categories.models import Category
from server.apps.geometries.models import (
    CategoryExtraSchema,
    GeoPlace,
    GeoPlaceCategory,
)
from server.apps.licenses.models import License
from server.apps.organizations.models import Organization

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
        assert resta.identifier == "rm-rename-group.restaurant"
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

        # availability rows typed on the legacy row — the round-3
        # staging failure: both hut_type FKs were outside every audit
        # (now covered by the catalog-driven sweep)
        checked = timezone.now()
        self.availability = HutAvailability.objects.create(
            hut=self.hut,
            availability_date=date(2026, 7, 1),
            free=5,
            total=10,
            occupancy_percent=50.0,
            occupancy_status="unknown",
            reservation_status="unknown",
            first_checked=checked,
            last_checked=checked,
            source_organization=Organization.objects.get(slug="wodore"),
            hut_type=self.resta,
        )
        self.availability_history = HutAvailabilityHistory.objects.create(
            hut=self.hut,
            availability_date=date(2026, 7, 1),
            free=5,
            total=10,
            occupancy_percent=50.0,
            occupancy_status="unknown",
            reservation_status="unknown",
            first_checked=checked,
            last_checked=checked,
            hut_type=self.resta,
        )

        # legacy extra schema rides the merge
        CategoryExtraSchema.objects.create(
            category=self.resta, schema={"type": "object"}
        )

        # the parent's default pointer + a license ride along too
        # (one instance: set + save — two calls would save a stale row)
        parent = _accommodation()
        parent.default = self.resta
        parent.save(update_fields=["default"])
        self.license = License.objects.create(name="Rm licence", category=self.resta)

    def test_merge_repoints_and_deletes(self) -> None:
        MIGRATION.rename_resta_to_restaurant(global_apps, None)

        # legacy row gone, survivor intact
        assert not Category.objects.filter(slug="resta").exists()
        self.restaurant.refresh_from_db()
        assert self.restaurant.slug == "restaurant"
        assert self.restaurant.identifier == "accommodation.restaurant"

        # parent default + license re-pointed
        assert _accommodation().default.pk == self.restaurant.pk  # type: ignore[union-attr]  # SET_NULL FK: None after deletion
        self.license.refresh_from_db()
        assert self.license.category_id == self.restaurant.pk

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

        # availability hut_type FKs re-pointed (round-3 staging failure)
        self.availability.refresh_from_db()
        assert self.availability.hut_type_id == self.restaurant.pk
        self.availability_history.refresh_from_db()
        assert self.availability_history.hut_type_id == self.restaurant.pk

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
        # back (identifier carried along — computed handlers are
        # inert in real runs), every re-pointed reference rides on it
        self.restaurant.refresh_from_db()
        assert self.restaurant.slug == "resta"
        assert self.restaurant.identifier == "accommodation.resta"
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


class TestStragglerGuard:
    """The pre-delete guard: zero stragglers passes, remaining
    references raise with an actionable listing (the synthetic-FK
    variant is impractical in tests — the catalog result is
    monkeypatched instead, per the review's allowance)."""

    def test_guard_raises_with_listing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import re

        restaurant = _cat("restaurant", order=10)
        resta = _cat("resta", order=100)

        def fake_stragglers(_cursor: Any, _resta_pk: int) -> list[tuple[str, str, int]]:
            return [("public.some_table", "some_col", 3)]

        monkeypatch.setattr(MIGRATION, "_category_stragglers", fake_stragglers)

        with pytest.raises(
            RuntimeError,
            match=re.escape("public.some_table.some_col: 3 row(s)"),
        ):
            MIGRATION._merge_resta_into_restaurant(resta, restaurant, global_apps)
        # nothing was deleted — the guard fired first
        assert Category.objects.filter(pk=resta.pk).exists()


class TestHistoricalRegistry:
    """The staging rehearsal with the registry the REAL migration
    runner passes: StateApps proxies built from the migration graph
    (all leaves) — computed-fields post_save handlers are registered
    on the live model classes only, so they are INERT here exactly
    like in production (the blocking Claude-review finding: the
    rename used to leave the stored identifier stale).

    Covers both branches:
    - merge: resta + restaurant both exist — re-points and survives
      unique_slug_per_parent;
    - rename-only: resta alone under an isolated parent — the stored
      identifier must update explicitly.
    """

    @pytest.fixture(autouse=True)
    def _state_apps(self) -> None:
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(connection, replace_migrations=False)
        # state after every migration (0024 is data-only — the model
        # shapes equal the pre-0024 shapes the runner would pass)
        state = loader.project_state(nodes=loader.graph.leaf_nodes())
        self.apps = state.apps

    def test_merge_and_rename_via_state_registry(self) -> None:
        # --- merge shape (staging) ---
        restaurant = _cat("restaurant", order=10)
        resta = _cat("resta", order=100)
        place = _make_place("Rm Gamma", "rm-gamma", kind=resta)
        GeoPlaceCategory.objects.create(
            geo_place=place, category=resta, classifier=_mode("standard")
        )
        hut = HutFactory(hut_type_open=resta)
        checked = timezone.now()
        availability = HutAvailability.objects.create(
            hut=hut,
            availability_date=date(2026, 7, 1),
            free=5,
            total=10,
            occupancy_percent=50.0,
            occupancy_status="unknown",
            reservation_status="unknown",
            first_checked=checked,
            last_checked=checked,
            source_organization=Organization.objects.get(slug="wodore"),
            hut_type=resta,
        )

        MIGRATION.rename_resta_to_restaurant(self.apps, None)

        assert not Category.objects.filter(
            slug="resta", parent=_accommodation()
        ).exists()
        place.refresh_from_db()
        assert place.kind_id == restaurant.pk
        # the catalog sweep re-pointed the availability FK too — under
        # the exact registry the real migration runner uses
        availability.refresh_from_db()
        assert availability.hut_type_id == restaurant.pk
        restaurant.refresh_from_db()
        assert restaurant.identifier == "accommodation.restaurant"

        # --- rename-only shape (the production path) ---
        isolated_resta = Category.objects.create(
            slug="resta", parent=_isolated_parent(), name="resta", order=100
        )

        MIGRATION.rename_resta_to_restaurant(self.apps, None)

        isolated_resta.refresh_from_db()
        assert isolated_resta.slug == "restaurant"
        # the stored computed identifier must not rely on
        # computedfields post_save hooks (inert on state proxies)
        assert isolated_resta.identifier == "rm-rename-group.restaurant"
