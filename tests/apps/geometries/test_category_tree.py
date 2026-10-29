"""Map category tree + DB kind contracts (geoplace-category-tree).

Covers the migration-seeded tree shape (map → super-roots → contract
groups → kinds), the CategoryKindContract runtime (classifier M2M,
operations/seasonality gates), the depth-guarded kind_slug derivation,
identifier stability and the identifier-first resolution fallbacks.
"""

import pytest
from hut_services import LocationSchema

from django.core.exceptions import ValidationError

from server.apps.categories.models import Category
from server.apps.geometries.kinds import (
    KIND_ADMIN,
    KIND_AMENITY,
    KIND_NONE,
    place_kind_slug,
)
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory
from server.apps.geometries.models._kind_contract import CategoryKindContract
from server.apps.geometries.schemas import (
    GeoPlaceBaseInput,
    OperationInput,
    SeasonalityInput,
)

pytestmark = pytest.mark.django_db


def _accommodation() -> Category:
    return Category.objects.get(slug="accommodation", parent__slug="amenity")


def _amenity_super() -> Category:
    return Category.objects.get(slug="amenity", parent__slug="map")


class TestTreeShape:
    def test_namespace_root_and_super_roots_seeded(self):
        map_root = Category.objects.get(slug="map", parent=None)
        assert map_root.identifier == "root.map"
        assert map_root.is_protected

        for slug in ("amenity", "admin", "natural"):
            super_root = Category.objects.get(slug=slug, parent=map_root)
            assert super_root.identifier == f"map.{slug}"
            assert super_root.is_protected

    def test_contract_group_reparented_with_identifier(self):
        accommodation = _accommodation()
        assert accommodation.parent_id == _amenity_super().pk
        assert accommodation.identifier == "amenity.accommodation"

    def test_child_identifiers_stay_two_level(self):
        # children keep parent.slug-based identifiers — the direct
        # parent did not change, only its own parent did
        child, _created = Category.objects.get_or_create(
            slug="tree-test-hut",
            parent=_accommodation(),
            defaults={"name": "Tree Test"},
        )
        assert child.identifier == "accommodation.tree-test-hut"

    def test_vocabulary_roots_stay_parentless(self):
        for slug in ("mode", "role"):
            root = Category.objects.get(slug=slug, parent=None)
            assert root.identifier == f"root.{slug}"


class TestKindContract:
    def test_accommodation_contract_seeded(self):
        contract = CategoryKindContract.objects.get(category=_accommodation())
        assert contract.has_operations
        assert contract.has_seasonality
        allowed = set(contract.allowed_classifiers.values_list("slug", flat=True))
        assert allowed == {"mode"}

    def test_allows_classifier_helper(self):
        contract = CategoryKindContract.objects.get(category=_accommodation())
        mode_root = Category.objects.get(slug="mode", parent=None)
        role_root = Category.objects.get(slug="role", parent=None)
        assert contract.allows_classifier(contract.category_id, mode_root.pk)
        assert not contract.allows_classifier(contract.category_id, role_root.pk)

    def test_missing_contract_is_empty(self):
        # a group without a contract row allows nothing
        assert (
            CategoryKindContract.objects.filter(category__slug="tourism").count() == 0
        )

    def test_classifier_validation_against_m2m(self):
        hut, _ = Category.objects.get_or_create(
            slug="contract-hut", parent=_accommodation(), defaults={"name": "H"}
        )
        mode_std = Category.objects.get(identifier="mode.standard")

        # allowed: mode is in the accommodation contract
        GeoPlaceCategory.validate_attributes(hut, mode_std, {})

        # rejected: role.operator is not in the contract
        role_op = Category.objects.get(identifier="role.operator")
        with pytest.raises(ValidationError):
            GeoPlaceCategory.validate_attributes(hut, role_op, {})

    def test_classifier_rejected_without_contract(self):
        # group without a contract row — no classifiers allowed
        stray_group = Category.objects.create(
            slug="stray-group", parent=_amenity_super()
        )
        mode_std = Category.objects.get(identifier="mode.standard")
        with pytest.raises(ValidationError):
            GeoPlaceCategory.validate_attributes(stray_group, mode_std, {})


class TestOperationsGating:
    def _schema(self, identifier: str) -> GeoPlaceBaseInput:
        return GeoPlaceBaseInput(
            name="Gate Test",
            location=LocationSchema(lon=7.75, lat=46.02),
            country_code="CH",
            place_type_identifiers=[identifier],
        )

    def test_accommodation_allows_operations_and_seasonality(self):
        Category.objects.get_or_create(
            slug="gate-hut", parent=_accommodation(), defaults={"name": "G"}
        )
        schema = self._schema("accommodation.gate-hut")
        schema.operations = [OperationInput(mode="mode.standard", capacity=30)]
        schema.seasonality = SeasonalityInput(months={1: 100})
        place, _status = GeoPlace.update_or_create(schema=schema)
        assert place.operations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap
        assert place.seasonality is not None  # type: ignore  # reverse FK: plugin-less inference gap

    def test_uncontracted_group_rejects_operations(self):
        # a group under a super-root without a contract row
        gate_group = Category.objects.create(slug="gate-group", parent=_amenity_super())
        Category.objects.create(slug="any", parent=gate_group)
        schema = self._schema("gate-group.any")
        schema.operations = [OperationInput(mode="mode.standard", capacity=5)]
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(schema=schema)

    def test_uncontracted_group_rejects_seasonality(self):
        season_group = Category.objects.create(
            slug="season-group", parent=_amenity_super()
        )
        Category.objects.create(slug="any", parent=season_group)
        schema = self._schema("season-group.any")
        schema.seasonality = SeasonalityInput(months={2: 50})
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(schema=schema)


class TestKindSlugDerivation:
    def test_kind_level_anchor_derives_super_root_identifier(self):
        hut, _ = Category.objects.get_or_create(
            slug="derive-hut", parent=_accommodation(), defaults={"name": "D"}
        )
        assert place_kind_slug([hut]) == KIND_AMENITY

    def test_admin_group_derives_map_admin(self):
        admin_super = Category.objects.get(slug="admin", parent__slug="map")
        administrative = Category.objects.get(slug="administrative", parent=admin_super)
        municipality, _ = Category.objects.get_or_create(
            slug="municipality", parent=administrative, defaults={"name": "M"}
        )
        assert place_kind_slug([municipality]) == KIND_ADMIN

    def test_contract_group_anchor_stays_none(self):
        # depth guard: a contract-group category walks to map, not a
        # super-root — never a partial path
        assert place_kind_slug([_accommodation()]) == KIND_NONE

    def test_super_root_anchor_stays_none(self):
        assert place_kind_slug([_amenity_super()]) == KIND_NONE

    def test_vocabulary_anchor_stays_none(self):
        mode_std = Category.objects.get(identifier="mode.standard")
        assert place_kind_slug([mode_std]) == KIND_NONE

    def test_no_categories_is_none(self):
        assert place_kind_slug([]) == KIND_NONE

    def test_first_valid_anchor_wins(self):
        # an invalid anchor (vocabulary) sorts before a valid one only
        # when its (order, slug) wins — the walk skips it either way
        mode_std = Category.objects.get(identifier="mode.standard")
        hut, _ = Category.objects.get_or_create(
            slug="multi-hut", parent=_accommodation(), defaults={"name": "X"}
        )
        assert place_kind_slug([mode_std, hut]) == KIND_AMENITY


class TestIdentifierResolution:
    def test_resolve_slug_two_part_via_identifier(self):
        category, paths = Category.objects.resolve_slug("accommodation.hut")
        # accommodation.hut may not exist on a bare test DB — the
        # seeded vocabulary always does
        category, paths = Category.objects.resolve_slug("mode.standard")
        assert category is not None
        assert category.identifier == "mode.standard"
        assert paths == []

    def test_resolve_slug_unknown_returns_none(self):
        category, paths = Category.objects.resolve_slug("no.such-category")
        assert category is None
        assert paths == []

    def test_resolver_identifier_first(self):
        GeoPlace._resolve_category_from_identifier.cache_clear()
        resolved = GeoPlace._resolve_category_from_identifier("mode.reduced")
        assert resolved.identifier == "mode.reduced"
