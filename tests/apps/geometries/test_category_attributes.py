"""Tests for GeoPlaceCategory association attributes.

OpenSpec change: ``geoplace-capacity-and-types-via-categories`` —
pins the season vocabulary seed (migration 0057, task 1.1), the
association validation contract (task 1.3), the schema write path
including the update-path refresh of *existing* associations
(tasks 2.1/2.3 — advisor review finding 1: additive-only used to
skip them, which would have made the backfill a no-op), the
exhaustive ``hut_type_closed`` mapping (task 2.2 — finding 2), the
API presenter payload (task 3.1), the tiles view (task 3.2) and the
admin inline form (task 3.3).
"""

import json
from typing import Any

import pytest
from hut_services import HutTypeEnum, LocationSchema

from tests.factories import CategoryFactory
from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory
from tests.factories.owners import OwnerFactory

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.forms import inlineformset_factory
from django.test import RequestFactory

from server.apps.categories.models import Category
from server.apps.geometries.admin import GeoPlaceAdmin
from server.apps.geometries.admin._geoplace import GeoPlaceCategoryInlineForm
from server.apps.geometries.models import GeoPlace, GeoPlaceCategory
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
    teardown. Production data is committed, so the cache is safe
    there; tests must reset it."""
    GeoPlace._resolve_category_from_identifier.cache_clear()
    GeoPlace._get_organization_by_slug.cache_clear()


def season(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="season")


@pytest.fixture
def hut_category() -> Category:
    """An accommodation.hut category (root exists via categories 0002)."""
    parent = Category.objects.get(slug="accommodation", parent__isnull=True)
    category, _created = Category.objects.get_or_create(
        slug="hut", parent=parent, defaults={"name": "Hütte"}
    )
    return category


def schema_for(
    category: Category,
    *,
    classifier: str | None = None,
    extra: dict[str, Any] | None = None,
    name: str = "Test Hut",
) -> GeoPlaceBaseInput:
    return GeoPlaceBaseInput(
        name=name,
        location=LocationSchema(lon=8.0, lat=46.5),
        country_code="CH",
        importance=80,
        place_type_identifiers=[
            PlaceTypeInput(
                identifier=category.identifier,
                classifier=classifier,
                extra=extra or {},
            )
        ],
    )


class TestSeasonVocabulary:
    def test_vocabulary_seeded_by_migration(self):
        parent = Category.objects.get(slug="season", parent__isnull=True)
        assert parent.is_active
        assert parent.name  # German source name seeded

        children = list(
            parent.children.order_by("order").values_list("slug", flat=True)
        )
        assert children == [
            "winter_room",
            "self_service",
            "year_round",
            "closed",
            "summer_only",
        ]

        # The computed identifier column must be populated — data
        # migrations create rows through historical models, so
        # computedfields never fires (categories' 0006 precedent).
        assert parent.identifier == "root.season"
        for child in parent.children.all():
            assert child.identifier == f"season.{child.slug}"
            assert child.is_active
            assert child.name
            assert child.i18n.get("name_en")  # English translation seeded


class TestGeoPlaceCategoryValidation:
    def test_valid_association_passes_clean(self, hut_category: Category):
        place = GeoPlaceFactory()
        association = GeoPlaceCategory(
            geo_place=place,
            category=hut_category,
            classifier=season("winter_room"),
            extra={"capacity_open": 40, "capacity_closed": 12},
        )
        association.full_clean()
        association.save()

        assert place.category_associations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap

    def test_clean_rejects_season_parent_itself(self):
        parent = Category.objects.get(slug="season", parent__isnull=True)
        association = GeoPlaceCategory(
            geo_place=GeoPlaceFactory(),
            category=CategoryFactory(),
            classifier=parent,
        )
        with pytest.raises(ValidationError):
            association.clean()

    def test_clean_rejects_child_of_other_subtree(self):
        other_parent = Category.objects.create(slug="other-vocab")
        other_child = Category.objects.create(slug="other-child", parent=other_parent)
        association = GeoPlaceCategory(
            geo_place=GeoPlaceFactory(),
            category=CategoryFactory(),
            classifier=other_child,
        )
        with pytest.raises(ValidationError):
            association.clean()

    @pytest.mark.parametrize(
        "value",
        [-1, "40", 1.5, True],
    )
    def test_bad_capacity_rejected(self, value: Any):
        with pytest.raises(ValidationError):
            GeoPlaceCategory.validate_extra({"capacity_open": value})

    def test_none_and_unknown_capacity_keys(self):
        # None-valued capacity keys are dropped, unknown keys preserved
        extra = GeoPlaceCategory.normalize_extra(
            {"capacity_open": 40, "capacity_closed": None, "curated": True}
        )
        assert extra == {"capacity_open": 40, "curated": True}

    def test_valid_capacities_pass(self):
        GeoPlaceCategory.validate_extra(
            {"capacity_open": 0, "capacity_closed": 12}
        )  # no raise
        GeoPlaceCategory.validate_extra({"capacity_open": None})  # dropped key


class TestSchemaWritePath:
    """GeoPlace.update_or_create writes association attributes (2.1)."""

    def _source(self) -> SourceInput:
        return SourceInput(slug="wodore", source_id="test-hut-1")

    def test_create_writes_classifier_and_extra(self, hut_category: Category):
        place, status = GeoPlace.update_or_create(
            schema=schema_for(
                hut_category,
                classifier="season.self_service",
                extra={"capacity_open": 40, "capacity_closed": None},
            ),
            from_source=self._source(),
        )

        assert status == UpdateCreateStatus.created
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.category == hut_category
        assert association.classifier == season("self_service")
        # the None-valued key was dropped, not stored
        assert association.extra == {"capacity_open": 40}

    def test_update_refreshes_existing_association(self, hut_category: Category):
        """Advisor finding 1: the backfill's core guarantee — existing
        associations get their classifier/extra updated, not skipped."""
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(hut_category, extra={"capacity_open": 30}),
            from_source=self._source(),
        )
        assert place.category_associations.get().extra == {"capacity_open": 30}  # type: ignore  # reverse FK

        place, status = GeoPlace.update_or_create(
            schema=schema_for(
                hut_category,
                classifier="season.closed",
                extra={"capacity_open": 40, "capacity_closed": 8},
            ),
            from_source=self._source(),
        )

        assert status == UpdateCreateStatus.updated
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.classifier == season("closed")
        assert association.extra == {"capacity_open": 40, "capacity_closed": 8}

    def test_update_drops_unpublished_capacity_keeps_unknown_keys(
        self, hut_category: Category
    ):
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(
                hut_category,
                extra={"capacity_open": 30, "capacity_closed": 8},
            ),
            from_source=self._source(),
        )
        # an editor added an unknown key (imports never write those)
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        association.extra = {"capacity_open": 30, "capacity_closed": 8, "note": "x"}
        association.save(update_fields=["extra"])

        place, _status = GeoPlace.update_or_create(
            schema=schema_for(hut_category, extra={"capacity_open": 31}),
            from_source=self._source(),
        )

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        # capacity_closed no longer published → dropped; unknown key kept
        assert association.extra == {"capacity_open": 31, "note": "x"}

    def test_import_path_validates_too(self, hut_category: Category):
        """Spec: invalid attributes raise on the schema path — Django
        never calls clean() there."""
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(
                schema=schema_for(
                    hut_category,
                    classifier="role.brand",  # not a season.* child
                ),
                from_source=self._source(),
            )
        with pytest.raises(ValidationError):
            GeoPlace.update_or_create(
                schema=schema_for(hut_category, extra={"capacity_open": -1}),
                from_source=self._source(),
            )

    def test_protected_place_untouched(self, hut_category: Category):
        place, _status = GeoPlace.update_or_create(
            schema=schema_for(hut_category, extra={"capacity_open": 30}),
            from_source=self._source(),
        )
        # manual category edit → flat protection (pre-existing admin
        # formset semantics)
        place.is_modified = True
        place.protected_fields = ["categories"]
        place.save(update_fields=["is_modified", "protected_fields"])

        place, status = GeoPlace.update_or_create(
            schema=schema_for(
                hut_category,
                classifier="season.closed",
                extra={"capacity_open": 99},
            ),
            from_source=self._source(),
        )

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.classifier is None
        assert association.extra == {"capacity_open": 30}


class TestWodoreImport:
    """import_geoplaces -s wodore rides the schema path (2.2/2.3)."""

    @pytest.fixture
    def command_mapping(self) -> dict[str, str | None]:
        from server.apps.geometries.management.commands.import_geoplaces import (
            Command,
        )

        return {slug: Command._CLOSED_TYPE_TO_SEASON.get(slug) for slug in HutTypeEnum}

    def test_mapping_is_exhaustive(self, command_mapping: dict[str, str | None]):
        """Every HutTypeEnum value has an explicit entry (advisor
        finding 2 — no hut silently loses its closed-type)."""
        enum_slugs = {member.value for member in HutTypeEnum}
        assert set(command_mapping) == enum_slugs

    @pytest.fixture(autouse=True)
    def only_my_huts(self):  # type: ignore[no-untyped-def]
        """The seeded test DB carries ~1700 huts — the import iterates
        all active ones. Deactivate everything so each test imports only
        the huts it creates (fast, deterministic). Harmless for the
        mapping tests (they never run the command)."""
        Hut.objects.filter(is_active=True).update(is_active=False)

    @pytest.mark.parametrize(
        ("closed_slug", "expected"),
        [
            ("selfhut", "season.self_service"),
            ("bivouac", "season.winter_room"),
            ("shelter", "season.winter_room"),
            ("closed", "season.closed"),
            ("camping", "season.summer_only"),
            ("resta", "season.summer_only"),
            ("hotel", "season.summer_only"),
            ("bhotel", "season.summer_only"),
            ("hostel", "season.summer_only"),
            ("unknown", None),
            ("special", None),
            ("hut", None),
            ("alp", None),
            ("campgr", None),
        ],
    )
    def test_closed_type_mapping(
        self, hut_category: Category, closed_slug: str, expected: str | None
    ):
        closed, _created = Category.objects.get_or_create(
            slug=closed_slug, parent=hut_category.parent
        )
        hut = HutFactory(hut_type_open=hut_category, hut_type_closed=closed)
        command = _import_command()
        assert command._season_classifier_identifier(hut) == expected

    def test_missing_closed_type_unstaffed_open_is_year_round(
        self, hut_category: Category
    ):
        for open_slug in ("selfhut", "shelter", "bivouac"):
            open_type, _created = Category.objects.get_or_create(
                slug=open_slug, parent=hut_category.parent
            )
            hut = HutFactory(hut_type_open=open_type, hut_type_closed=None)
            assert (
                _import_command()._season_classifier_identifier(hut)
                == "season.year_round"
            )

    def test_missing_closed_type_staffed_open_is_unknown(self, hut_category: Category):
        hut = HutFactory(hut_type_open=hut_category, hut_type_closed=None)
        assert _import_command()._season_classifier_identifier(hut) is None

    def test_full_import_via_schema_path(self, hut_category: Category):
        closed, _created = Category.objects.get_or_create(
            slug="selfhut", parent=hut_category.parent
        )
        hut = HutFactory(
            name="Cabane Test",
            hut_type_open=hut_category,
            hut_type_closed=closed,
            capacity_open=40,
            capacity_closed=12,
            hut_owner=OwnerFactory(),
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self_out())

        place = GeoPlace.objects.get(
            source_associations__organization__slug="wodore",
            source_associations__source_id=hut.slug,
        )
        association = place.category_associations.get(category=hut_category)  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.classifier == season("self_service")
        assert association.extra == {
            "capacity_open": 40,
            "capacity_closed": 12,
        }
        # the owner party still rides merge_owner (role.operator)
        assert place.party_associations.filter(  # type: ignore  # reverse FK: plugin-less inference gap
            role__identifier="role.operator"
        ).exists()
        assert place.importance == 80

    def test_hut_without_closed_type_or_capacities(self, hut_category: Category):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_open=None,
            capacity_closed=None,
        )

        call_command("import_geoplaces", "-s", "wodore", stdout=self_out())

        place = GeoPlace.objects.get(
            source_associations__organization__slug="wodore",
            source_associations__source_id=hut.slug,
        )
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.classifier is None  # staffed open type → unknown
        assert association.extra == {}

    def test_rerun_update_respects_protection(self, hut_category: Category):
        hut = HutFactory(hut_type_open=hut_category, capacity_open=40)
        call_command("import_geoplaces", "-s", "wodore", stdout=self_out())
        place = GeoPlace.objects.get(
            source_associations__organization__slug="wodore",
            source_associations__source_id=hut.slug,
        )

        # manual capacity edit (admin formset marks the place)
        place.is_modified = True
        place.protected_fields = ["categories"]
        place.save(update_fields=["is_modified", "protected_fields"])

        hut.capacity_open = 99
        Hut.objects.filter(pk=hut.pk).update(capacity_open=99)
        call_command("import_geoplaces", "-s", "wodore", "--update", stdout=self_out())

        place.refresh_from_db()
        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.extra == {"capacity_open": 40}  # untouched


class TestApiPayload:
    """build_categories_data feeds search/nearby/place-detail (3.1)."""

    def test_category_entry_carries_attributes(
        self, hut_category: Category, rf: RequestFactory
    ):
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut_category,
            classifier=season("winter_room"),
            extra={"capacity_open": 12},
        )

        data = build_categories_data(place, rf.get("/"))

        assert data == [
            {
                "slug": "hut",
                "name": hut_category.name_i18n,
                "description": hut_category.description_i18n,
                "classifier": "season.winter_room",
                "extra": {"capacity_open": 12},
            }
        ]


class TestTilesView:
    def test_categories_json_carries_classifier_and_extra(self, hut_category: Category):
        from django.db import connection

        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place,
            category=hut_category,
            classifier=season("closed"),
            extra={"capacity_open": 20},
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
        assert entry["classifier"] == "season.closed"
        assert entry["extra"] == {"capacity_open": 20}


class TestAdminInline:
    """Capacity fields render, validate and write into extra (3.3)."""

    def _formset_class(self):  # type: ignore[no-untyped-def]
        return inlineformset_factory(
            GeoPlace,
            GeoPlaceCategory,
            form=GeoPlaceCategoryInlineForm,
            fields=("category", "classifier", "capacity_open", "capacity_closed"),
            extra=1,
        )

    def test_capacity_fields_write_into_extra(self, hut_category: Category):
        place = GeoPlaceFactory()
        FormSet = self._formset_class()
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-category": str(hut_category.pk),
            "form-0-capacity_open": "40",
            "form-0-capacity_closed": "8",
        }
        formset = FormSet(instance=place, data=data, prefix="form")
        assert formset.is_valid(), formset.errors
        formset.save()

        association = place.category_associations.get()  # type: ignore  # reverse FK: plugin-less inference gap
        assert association.extra == {"capacity_open": 40, "capacity_closed": 8}

    def test_initial_values_from_extra(self, hut_category: Category):
        place = GeoPlaceFactory()
        GeoPlaceCategory.objects.create(
            geo_place=place, category=hut_category, extra={"capacity_open": 40}
        )
        FormSet = self._formset_class()
        formset = FormSet(instance=place)

        form = formset.forms[0]
        assert (
            form.get_initial_for_field(form.fields["capacity_open"], "capacity_open")
            == 40
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
            "form-0-capacity_open": "-3",
        }
        formset = FormSet(instance=place, data=data, prefix="form")
        assert not formset.is_valid()

    def test_formset_save_marks_place_modified(
        self, hut_category: Category, rf: RequestFactory
    ):
        """Pre-existing flat protection (save_formset): a category
        formset edit marks is_modified + protects 'categories'."""
        place = GeoPlaceFactory(category_list=[hut_category])
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
            "form-0-capacity_open": "12",
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


def _import_command():  # type: ignore[no-untyped-def]
    from server.apps.geometries.management.commands.import_geoplaces import (
        Command,
    )

    return Command()


def self_out():  # type: ignore[no-untyped-def]
    import io

    return io.StringIO()
