"""Tests for GeoPlaceCategory operating modes and extra schemas.

OpenSpec change ``geoplace-capacity-and-types-via-categories``
(revised design): pins the ``mode`` vocabulary seed (migration 0058),
the ``CategoryExtraSchema`` guardrails (metaschema check,
``additionalProperties`` rejection, fail-open on corrupt rows), the
schema-driven association validation, the two-association
operating-mode write path — including the update-path refresh keyed
per ``(category, mode)`` (advisor review finding 1) and the
same-category standard+reduced pair allowed by the new unique
constraint (advisor P0) — the exhaustive wodore mapping (finding 2),
API/tiles surfaces and the schema-driven admin form.
"""

import json
from typing import Any

import pytest
from hut_services import LocationSchema

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory
from tests.factories.owners import OwnerFactory

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.forms import inlineformset_factory
from django.test import RequestFactory

from server.apps.categories.models import Category
from server.apps.geometries.admin import GeoPlaceAdmin
from server.apps.geometries.admin._geoplace import GeoPlaceCategoryInlineForm
from server.apps.geometries.models import (
    CategoryExtraSchema,
    GeoPlace,
    GeoPlaceCategory,
    resolve_extra_schema,
)
from server.apps.geometries.presenters import build_categories_data
from server.apps.geometries.schemas import (
    GeoPlaceBaseInput,
    PlaceTypeInput,
    SourceInput,
)
from server.apps.huts.models import Hut
from server.core import UpdateCreateStatus

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_identifier_caches() -> None:
    """``GeoPlace._resolve_category_from_identifier`` and
    ``_get_organization_by_slug`` are process-wide lru caches; without
    clearing, a category created in one test (and rolled back) is
    served stale into the next test — the deferred FK then fails at
    teardown."""
    GeoPlace._resolve_category_from_identifier.cache_clear()
    GeoPlace._get_organization_by_slug.cache_clear()


def mode(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="mode")


@pytest.fixture
def accommodation_root() -> Category:
    return Category.objects.get(slug="accommodation", parent__isnull=True)


@pytest.fixture
def hut_category(accommodation_root: Category) -> Category:
    category, _created = Category.objects.get_or_create(
        slug="hut", parent=accommodation_root, defaults={"name": "Hütte"}
    )
    return category


@pytest.fixture
def selfhut_category(accommodation_root: Category) -> Category:
    category, _created = Category.objects.get_or_create(
        slug="selfhut",
        parent=accommodation_root,
        defaults={"name": "Selbstversorgerhütte"},
    )
    return category


@pytest.fixture
def unknown_category(accommodation_root: Category) -> Category:
    category, _created = Category.objects.get_or_create(
        slug="unknown", parent=accommodation_root, defaults={"name": "Unbekannt"}
    )
    return category


def schema_for(
    *place_types: PlaceTypeInput,
    name: str = "Test Hut",
) -> GeoPlaceBaseInput:
    return GeoPlaceBaseInput(
        name=name,
        location=LocationSchema(lon=8.0, lat=46.5),
        country_code="CH",
        importance=80,
        place_type_identifiers=list(place_types),
    )


def standard(category: Category, **extra: Any) -> PlaceTypeInput:
    return PlaceTypeInput(
        identifier=category.identifier, classifier="mode.standard", extra=extra
    )


def reduced(category: Category, **extra: Any) -> PlaceTypeInput:
    return PlaceTypeInput(
        identifier=category.identifier, classifier="mode.reduced", extra=extra
    )


class TestModeVocabulary:
    def test_vocabulary_seeded_by_migration(self):
        parent = Category.objects.get(slug="mode", parent__isnull=True)
        assert parent.is_active
        assert parent.name  # German source name seeded

        children = list(
            parent.children.order_by("order").values_list("slug", flat=True)
        )
        assert children == ["standard", "reduced"]

        # The computed identifier column must be populated — data
        # migrations create rows through historical models, so
        # computedfields never fires (categories' 0006 precedent).
        assert parent.identifier == "root.mode"
        for child in parent.children.all():
            assert child.identifier == f"mode.{child.slug}"
            assert child.is_active
            assert child.name
            assert child.i18n.get("name_en")  # English translation seeded


class TestCategoryExtraSchema:
    def test_accommodation_schema_seeded_by_migration(
        self, accommodation_root: Category
    ):
        schema_row = CategoryExtraSchema.objects.get(category=accommodation_root)
        props = schema_row.schema["properties"]
        assert "capacity" in props
        assert props["capacity"]["type"] == ["integer", "null"]

    def test_valid_schema_passes_clean(self, hut_category: Category):
        row = CategoryExtraSchema(
            category=hut_category,
            schema={"type": "object", "properties": {"rooms": {"type": "integer"}}},
        )
        row.full_clean()  # no raise

    def test_invalid_schema_rejected(self, hut_category: Category):
        row = CategoryExtraSchema(category=hut_category, schema={"type": "not-a-type"})
        with pytest.raises(ValidationError):
            row.full_clean()

    def test_strict_additional_properties_rejected(self, hut_category: Category):
        row = CategoryExtraSchema(
            category=hut_category,
            schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
        with pytest.raises(ValidationError):
            row.full_clean()

    def test_resolution_own_schema_first_then_parent(
        self, accommodation_root: Category, hut_category: Category
    ):
        # seeded parent schema is inherited by children
        assert resolve_extra_schema(hut_category) == resolve_extra_schema(
            accommodation_root
        )
        # an own schema wins over the parent's
        own = CategoryExtraSchema.objects.create(
            category=hut_category, schema={"type": "object", "properties": {}}
        )
        assert resolve_extra_schema(hut_category) == own
        # unrelated subtrees resolve to nothing
        other = Category.objects.create(slug="other-root")
        assert resolve_extra_schema(other) is None

    def test_corrupt_schema_fails_open(self, hut_category: Category):
        """Advisor guardrail: a corrupt stored schema (written past
        ``clean()``) must not brick writes — validation degrades to a
        no-op with a loud log."""
        row = CategoryExtraSchema.objects.create(
            category=hut_category, schema={"type": "not-a-type"}
        )
        assert row.compiled_validator() is None
        GeoPlaceCategory.validate_extra(hut_category, {"anything": "goes"})  # no raise

    def test_validator_cache_invalidated_on_edit(self, accommodation_root: Category):

        row = CategoryExtraSchema.objects.get(category=accommodation_root)
        first = row.compiled_validator()
        assert first is not None
        row.schema = {
            **row.schema,
            "properties": {**row.schema["properties"], "water": {"type": "string"}},
        }
        row.save()
        # ``modified`` is trigger-updated (not Python auto_now) — reload
        # to see the new cache key component.
        row.refresh_from_db()
        second = row.compiled_validator()
        assert second is not None
        assert second is not first


class TestGeoPlaceCategoryValidation:
    def test_valid_association_passes_clean(self, hut_category: Category):
        association = GeoPlaceCategory(
            geo_place=GeoPlaceFactory(),
            category=hut_category,
            classifier=mode("standard"),
            extra={"capacity": 40},
        )
        association.full_clean()  # schema (seeded) validates capacity
        association.save()

    def test_clean_rejects_mode_parent_itself(self):
        parent = Category.objects.get(slug="mode", parent__isnull=True)
        association = GeoPlaceCategory(
            geo_place=GeoPlaceFactory(),
            category=Category.objects.create(slug="loose-cat"),
            classifier=parent,
        )
        with pytest.raises(ValidationError):
            association.clean()

    def test_clean_rejects_child_of_other_subtree(self):
        other_parent = Category.objects.create(slug="other-vocab")
        other_child = Category.objects.create(slug="other-child", parent=other_parent)
        association = GeoPlaceCategory(
            geo_place=GeoPlaceFactory(),
            category=Category.objects.create(slug="loose-cat-2"),
            classifier=other_child,
        )
        with pytest.raises(ValidationError):
            association.clean()

    @pytest.mark.parametrize("value", [-1, "40", 1.5, True])
    def test_schema_violations_rejected(self, hut_category: Category, value: Any):
        with pytest.raises(ValidationError):
            GeoPlaceCategory.validate_extra(hut_category, {"capacity": value})

    def test_unknown_keys_pass_and_none_dropped(self, hut_category: Category):
        # unknown keys are preserved (additionalProperties permissive)
        GeoPlaceCategory.validate_extra(hut_category, {"curated": "yes"})  # no raise
        # None-valued keys are dropped on write, never stored as null
        assert GeoPlaceCategory.normalize_extra({"capacity": None, "x": 1}) == {"x": 1}

    def test_no_schema_free_form(self):
        free = Category.objects.create(slug="schemaless")
        GeoPlaceCategory.validate_extra(free, {"anything": ["at", "all"]})  # no raise


class TestSchemaWritePath:
    """GeoPlace.update_or_create writes mode associations (2.1)."""

    def _source(self) -> SourceInput:
        return SourceInput(slug="wodore", source_id="test-hut-1")

    def test_create_writes_both_modes(
        self, hut_category: Category, selfhut_category: Category
    ):
        place, status = GeoPlace.update_or_create(
            schema=schema_for(
                standard(hut_category, capacity=40),
                reduced(selfhut_category, capacity=12),
            ),
            from_source=self._source(),
        )

        assert status == UpdateCreateStatus.created
        associations = {
            (a.category.slug, a.classifier.identifier): a.extra  # type: ignore  # reverse FK prefetch gap
            for a in place.category_associations.all()  # type: ignore  # reverse FK: plugin-less inference gap
        }
        assert associations == {
            ("hut", "mode.standard"): {"capacity": 40},
            ("selfhut", "mode.reduced"): {"capacity": 12},
        }

    def test_same_category_both_modes_allowed(self, unknown_category: Category):
        """Advisor P0: open and closed type can coincide — the
        constraint keys on (place, category, mode), not category."""
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(
                standard(unknown_category, capacity=30),
                reduced(unknown_category, capacity=8),
            ),
            from_source=self._source(),
        )
        assert place.category_associations.count() == 2  # type: ignore  # reverse FK: plugin-less inference gap

    def test_update_refreshes_both_mode_rows(
        self, hut_category: Category, selfhut_category: Category
    ):
        """Advisor finding 1: existing rows refresh per (category,
        mode) — never clobber each other."""
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(
                standard(hut_category, capacity=30),
                reduced(selfhut_category, capacity=8),
            ),
            from_source=self._source(),
        )
        place, status = GeoPlace.update_or_create(
            schema=schema_for(
                standard(hut_category, capacity=40),
                reduced(selfhut_category, capacity=12),
            ),
            from_source=self._source(),
        )

        assert status == UpdateCreateStatus.updated
        associations = {
            (a.category.slug, a.classifier.identifier): a.extra  # type: ignore  # reverse FK prefetch gap
            for a in place.category_associations.all()  # type: ignore  # reverse FK: plugin-less inference gap
        }
        assert associations == {
            ("hut", "mode.standard"): {"capacity": 40},
            ("selfhut", "mode.reduced"): {"capacity": 12},
        }

    def test_update_schema_keys_replaced_others_preserved(self, hut_category: Category):
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(standard(hut_category, capacity=30)),
            from_source=self._source(),
        )
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        association.extra = {"capacity": 30, "note": "curated"}
        association.save(update_fields=["extra"])

        place, _status = GeoPlace.update_or_create(
            schema=schema_for(standard(hut_category)),
            from_source=self._source(),  # capacity no longer published
        )

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        # schema key dropped (unpublished), non-schema key preserved
        assert association.extra == {"note": "curated"}

    def test_import_path_validates_too(self, hut_category: Category):
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(
                schema=schema_for(
                    PlaceTypeInput(
                        identifier=hut_category.identifier,
                        classifier="role.brand",  # not a mode.* child
                    )
                ),
                from_source=self._source(),
            )
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(
                schema=schema_for(standard(hut_category, capacity=-1)),
                from_source=self._source(),
            )

    def test_protected_place_untouched(self, hut_category: Category):
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(standard(hut_category, capacity=30)),
            from_source=self._source(),
        )
        place.is_modified = True
        place.protected_fields = ["categories"]
        place.save(update_fields=["is_modified", "protected_fields"])

        place, _status = GeoPlace.update_or_create(
            schema=schema_for(standard(hut_category, capacity=99)),
            from_source=self._source(),
        )

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.extra == {"capacity": 30}


class TestUniqueConstraint:
    def test_duplicate_place_category_mode_rejected(self, hut_category: Category):
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place, category=hut_category, classifier=mode("standard")
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceCategory.objects.create(
                    geo_place=place,
                    category=hut_category,
                    classifier=mode("standard"),
                )

    def test_same_place_category_different_mode_allowed(self, hut_category: Category):
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place, category=hut_category, classifier=mode("standard")
        )
        GeoPlaceCategory.objects.create(  # no raise
            geo_place=place, category=hut_category, classifier=mode("reduced")
        )

    def test_duplicate_null_classifier_rejected(self, hut_category: Category):
        """``nulls_distinct=False``: two NULL-mode rows for one
        category are duplicates too."""
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(geo_place=place, category=hut_category)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceCategory.objects.create(geo_place=place, category=hut_category)


class TestWodoreImport:
    """import_geoplaces -s wodore rides the schema path (2.2/2.3)."""

    @pytest.fixture(autouse=True)
    def only_my_huts(self) -> None:
        """The seeded test DB can carry huts — the import iterates all
        active ones. Deactivate everything so each test imports only
        the huts it creates."""
        Hut.objects.filter(is_active=True).update(is_active=False)

    def _imported_place(self, hut: Hut) -> GeoPlace:
        return GeoPlace.objects.get(
            source_associations__organization__slug="wodore",
            source_associations__source_id=hut.slug,
        )

    def _associations(self, place: GeoPlace) -> dict[tuple[str, str], dict[str, Any]]:
        # Mode associations only — foreign rows (no classifier, e.g.
        # from other sources) are asserted on separately.
        return {
            (a.category.slug, a.classifier.identifier): a.extra  # type: ignore[union-attr]
            for a in place.category_associations.all()  # type: ignore  # reverse FK: plugin-less inference gap
            if a.classifier_id
        }

    def test_full_hut_two_mode_associations(
        self, hut_category: Category, selfhut_category: Category
    ):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=selfhut_category,
            capacity_open=40,
            capacity_closed=12,
            hut_owner=OwnerFactory(),
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        place = self._imported_place(hut)
        assert self._associations(place) == {
            ("hut", "mode.standard"): {"capacity": 40},
            ("selfhut", "mode.reduced"): {"capacity": 12},
        }
        # the owner party still rides merge_owner (role.operator)
        assert place.party_associations.filter(  # type: ignore  # reverse FK: plugin-less inference gap
            role__identifier="role.operator"
        ).exists()
        assert place.importance == 80

    def test_unknown_closed_type_with_capacity_carries_reduced(
        self, hut_category: Category, unknown_category: Category
    ):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=unknown_category,
            capacity_open=None,
            capacity_closed=10,
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        assert self._associations(self._imported_place(hut)) == {
            ("hut", "mode.standard"): {},
            ("unknown", "mode.reduced"): {"capacity": 10},
        }

    def test_no_closed_type_but_capacity_carries_reduced(
        self, hut_category: Category, unknown_category: Category
    ):
        # the unknown_category fixture ensures accommodation.unknown
        # exists — the reduced fallback resolves onto it.
        assert unknown_category.slug == "unknown"
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_open=None,
            capacity_closed=8,
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        assert self._associations(self._imported_place(hut)) == {
            ("hut", "mode.standard"): {},
            ("unknown", "mode.reduced"): {"capacity": 8},
        }

    def test_no_closed_info_single_association(self, hut_category: Category):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_open=None,
            capacity_closed=None,
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        assert self._associations(self._imported_place(hut)) == {
            ("hut", "mode.standard"): {}
        }

    def test_rerun_update_refreshes_without_duplicates(
        self, hut_category: Category, selfhut_category: Category
    ):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=selfhut_category,
            capacity_open=40,
        )
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())
        Hut.objects.filter(pk=hut.pk).update(capacity_open=44)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self._out())

        place = self._imported_place(hut)
        assert place.category_associations.count() == 2  # type: ignore  # reverse FK: plugin-less inference gap
        assert self._associations(place)[("hut", "mode.standard")] == {"capacity": 44}

    def test_rerun_dropped_mode_keeps_old_row(
        self, hut_category: Category, selfhut_category: Category
    ):
        """Additive semantics (review P1): a hut that stops publishing
        its reduced fact keeps the old reduced row — reconciliation is
        a documented follow-up."""
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=selfhut_category,
            capacity_open=40,
            capacity_closed=12,
        )
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())
        Hut.objects.filter(pk=hut.pk).update(hut_type_closed=None, capacity_closed=None)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self._out())

        place = self._imported_place(hut)
        assert self._associations(place) == {
            ("hut", "mode.standard"): {"capacity": 40},
            ("selfhut", "mode.reduced"): {"capacity": 12},  # stale, kept
        }

    def test_rerun_category_change_keeps_old_row(self, hut_category: Category):
        """Additive semantics (review P1): a type change accumulates
        the old association alongside the new one."""
        hut = HutFactory(hut_type_open=hut_category, capacity_open=40)
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())
        alp, _created = Category.objects.get_or_create(
            slug="alp", parent=hut_category.parent, defaults={"name": "Alphütte"}
        )
        Hut.objects.filter(pk=hut.pk).update(hut_type_open=alp)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self._out())

        place = self._imported_place(hut)
        assert self._associations(place) == {
            ("hut", "mode.standard"): {"capacity": 40},  # stale, kept
            ("alp", "mode.standard"): {"capacity": 40},
        }

    def test_foreign_association_untouched(self, hut_category: Category):
        """Associations from other sources/paths (e.g. OSM) are never
        pruned or rewritten by the wodore import."""
        hut = HutFactory(hut_type_open=hut_category, capacity_open=40)
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())
        place = self._imported_place(hut)
        restaurant, _created = Category.objects.get_or_create(
            slug="restaurant", defaults={"name": "Restaurant"}
        )
        foreign = GeoPlaceCategory.objects.create(
            geo_place=place, category=restaurant, extra={"note": "osm"}
        )

        Hut.objects.filter(pk=hut.pk).update(capacity_open=50)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self._out())

        foreign.refresh_from_db()
        assert foreign.extra == {"note": "osm"}  # untouched
        assert self._associations(place)[("hut", "mode.standard")] == {"capacity": 50}

    def test_rerun_update_respects_protection(self, hut_category: Category):
        hut = HutFactory(hut_type_open=hut_category, capacity_open=40)
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())
        place = self._imported_place(hut)

        place.is_modified = True
        place.protected_fields = ["categories"]
        place.save(update_fields=["is_modified", "protected_fields"])

        Hut.objects.filter(pk=hut.pk).update(capacity_open=99)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self._out())

        place.refresh_from_db()
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.extra == {"capacity": 40}  # untouched

    @staticmethod
    def _out() -> Any:
        import io

        return io.StringIO()


class TestApiPayload:
    """build_categories_data feeds search/nearby/place-detail (3.1)."""

    def test_entries_carry_mode_and_extra(
        self, hut_category: Category, selfhut_category: Category, rf: RequestFactory
    ):
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut_category,
            classifier=mode("standard"),
            extra={"capacity": 40},
        )
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=selfhut_category,
            classifier=mode("reduced"),
            extra={"capacity": 12},
        )

        data = build_categories_data(place, rf.get("/"))

        by_slug = {entry["slug"]: entry for entry in data}
        assert by_slug["hut"]["classifier"] == "mode.standard"
        assert by_slug["hut"]["extra"] == {"capacity": 40}
        assert by_slug["selfhut"]["classifier"] == "mode.reduced"
        assert by_slug["selfhut"]["extra"] == {"capacity": 12}


class TestTilesView:
    def test_categories_json_carries_classifier_and_extra(self, hut_category: Category):
        from django.db import connection

        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut_category,
            classifier=mode("standard"),
            extra={"capacity": 20},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT categories FROM geoplaces_for_tiles WHERE slug = %s",
                [place.slug],
            )
            row = cursor.fetchone()

        assert row is not None
        categories = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        entry = next(e for e in categories if e["slug"] == "hut")
        assert entry["classifier"] == "mode.standard"
        assert entry["extra"] == {"capacity": 20}


class TestAdminInline:
    """Schema-driven form: widget attachment + validation (3.3)."""

    def _formset_class(self):  # type: ignore[no-untyped-def]
        return inlineformset_factory(
            GeoPlace,
            GeoPlaceCategory,
            form=GeoPlaceCategoryInlineForm,
            fields=("category", "classifier", "extra"),
            extra=1,
        )

    def test_schema_widget_attached_for_schema_category(self, hut_category: Category):
        from unfold.widgets import UnfoldAdminJSONSchemaWidget

        place = GeoPlaceFactory()
        FormSet = self._formset_class()
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-category": str(hut_category.pk),
            "form-0-classifier": str(mode("standard").pk),
            "form-0-extra": json.dumps({"capacity": 40}),
        }
        formset = FormSet(instance=place, data=data, prefix="form")
        assert formset.is_valid(), formset.errors
        formset.save()

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.extra == {"capacity": 40}
        # the rendered form uses the schema widget (jedison editor)
        bound_form = FormSet(instance=place).forms[0]
        assert isinstance(
            bound_form.fields["extra"].widget, UnfoldAdminJSONSchemaWidget
        )

    def test_invalid_capacity_rejected(self, hut_category: Category):
        place = GeoPlaceFactory()
        FormSet = self._formset_class()
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-category": str(hut_category.pk),
            "form-0-classifier": str(mode("standard").pk),
            "form-0-extra": json.dumps({"capacity": -3}),
        }
        formset = FormSet(instance=place, data=data, prefix="form")
        assert not formset.is_valid()

    def test_formset_save_marks_place_modified(
        self, hut_category: Category, rf: RequestFactory
    ):
        """Pre-existing flat protection (save_formset): a category
        formset edit marks is_modified + protects 'categories'."""
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut_category,
            classifier=mode("standard"),
            extra={"capacity": 7},
        )
        admin_instance = GeoPlaceAdmin(GeoPlace, AdminSite())
        FormSet = self._formset_class()
        existing = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(existing.pk),
            "form-0-category": str(hut_category.pk),
            "form-0-classifier": str(mode("standard").pk),
            "form-0-extra": json.dumps({"capacity": 12}),
        }
        formset = FormSet(instance=place, data=data, prefix="form")
        assert formset.is_valid(), formset.errors
        from django.forms.models import modelform_factory

        PlaceForm = modelform_factory(GeoPlace, fields=["name"])
        admin_instance.save_formset(
            rf.post("/admin/"),
            form=PlaceForm(instance=place),
            formset=formset,
            change=True,
        )

        place.refresh_from_db()
        assert place.is_modified
        assert "categories" in (place.protected_fields or [])
        existing.refresh_from_db()
        assert existing.extra == {"capacity": 12}
