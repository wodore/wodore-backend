"""Typed operating facts and seasonality (geoplace-kinds-operations-graph).

Pins task 2.1/2.2/2.7: GeoPlaceOperation constraints + upserts,
GeoPlaceSeasonality range checks + MonthAccessor semantics, the
wodore seasonality import (fuzzy mapping, the PO-confirmed
below-100-no-reduced-type → accommodation.unknown rule), and the
operations protection key.
"""

from typing import Any

import pytest
from hut_services import LocationSchema

from tests.factories.geometries import GeoPlaceFactory
from tests.factories.huts import HutFactory

from django.core.management import call_command
from django.db import IntegrityError, transaction

from server.apps.categories.models import Category
from server.apps.geometries.models import (
    GeoPlace,
    GeoPlaceOperation,
    GeoPlaceSeasonality,
    Month,
    MonthAccessor,
)
from server.apps.geometries.schemas import (
    GeoPlaceBaseInput,
    OperationInput,
    SeasonalityInput,
    SourceInput,
)
from server.apps.huts.models import Hut

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_identifier_caches() -> None:
    GeoPlace._resolve_category_from_identifier.cache_clear()
    GeoPlace._get_organization_by_slug.cache_clear()


@pytest.fixture
def hut_category() -> Category:
    parent = Category.objects.get(slug="accommodation", parent__isnull=True)
    category, _created = Category.objects.get_or_create(
        slug="hut", parent=parent, defaults={"name": "Hütte"}
    )
    return category


def mode(slug: str) -> Category:
    return Category.objects.get(slug=slug, parent__slug="mode")


def _schema(
    operations: list[OperationInput], seasonality: Any = None
) -> GeoPlaceBaseInput:
    parent = Category.objects.get(slug="accommodation", parent__isnull=True)
    hut, _created = Category.objects.get_or_create(
        slug="hut", parent=parent, defaults={"name": "Hütte"}
    )
    return GeoPlaceBaseInput(
        name="Op Hut",
        location=LocationSchema(lon=8.0, lat=46.5),
        country_code="CH",
        importance=80,
        place_type_identifiers=[hut.identifier],
        operations=operations,
        seasonality=seasonality,
    )


class TestGeoPlaceOperation:
    def test_unique_per_place_and_mode(self):
        place = GeoPlaceFactory()
        GeoPlaceOperation.objects.create(
            geo_place=place, mode=mode("standard"), capacity=10
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceOperation.objects.create(
                    geo_place=place, mode=mode("standard"), capacity=20
                )

    def test_negative_capacity_rejected(self):
        place = GeoPlaceFactory()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GeoPlaceOperation.objects.create(
                    geo_place=place, mode=mode("standard"), capacity=-1
                )

    def test_create_and_refresh_via_schema_path(self):
        source = SourceInput(slug="wodore", source_id="op-hut-1")
        place, _status = GeoPlace.update_or_create(
            schema=_schema(
                [
                    OperationInput(mode="mode.standard", capacity=64),
                    OperationInput(mode="mode.reduced", capacity=8),
                ]
            ),
            from_source=source,
        )
        operations = {o.mode.identifier: o.capacity for o in place.operations.all()}  # type: ignore  # reverse FK: plugin-less inference gap
        assert operations == {"mode.standard": 64, "mode.reduced": 8}

        place, status = GeoPlace.update_or_create(
            schema=_schema(
                [
                    OperationInput(mode="mode.standard", capacity=70),
                    OperationInput(mode="mode.reduced", capacity=8),
                ]
            ),
            from_source=source,
        )
        assert status.value == "updated"
        operations = {o.mode.identifier: o.capacity for o in place.operations.all()}  # type: ignore  # reverse FK: plugin-less inference gap
        assert operations == {"mode.standard": 70, "mode.reduced": 8}

    def test_invalid_mode_identifier_rejected(self):
        from django.core.exceptions import ValidationError

        with pytest.raises((ValidationError, ValueError)):
            GeoPlace.update_or_create(
                schema=_schema(
                    [OperationInput(mode="role.brand", capacity=1)]  # not mode.*
                ),
                from_source=SourceInput(slug="wodore", source_id="op-hut-2"),
            )

    def test_operations_protection_key_blocks_updates(self):
        source = SourceInput(slug="wodore", source_id="op-hut-3")
        place, _status = GeoPlace.update_or_create(
            schema=_schema([OperationInput(mode="mode.standard", capacity=30)]),
            from_source=source,
        )
        place.protected_fields = ["operations"]
        place.save(update_fields=["protected_fields"])

        GeoPlace.update_or_create(
            schema=_schema([OperationInput(mode="mode.standard", capacity=99)]),
            from_source=source,
        )
        place.refresh_from_db()
        operations = {o.mode.identifier: o.capacity for o in place.operations.all()}  # type: ignore  # reverse FK: plugin-less inference gap
        assert operations == {"mode.standard": 30}  # untouched


class TestGeoPlaceSeasonality:
    def test_range_check_rejects_out_of_bounds(self):
        place = GeoPlaceFactory()
        row = GeoPlaceSeasonality.objects.create(geo_place=place)
        # the accessor guards first — write the column directly to hit
        # the DB CHECK constraint
        row.month_07 = 150
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                row.save()

    def test_accessor_round_trip_and_guards(self):
        place = GeoPlaceFactory()
        row = GeoPlaceSeasonality.objects.create(geo_place=place)
        row.months[Month.JULY] = 100
        row.months[Month.DECEMBER] = 0
        row.save()
        row.refresh_from_db()

        assert row.months[Month.JULY] == 100
        assert row.months[Month.DECEMBER] == 0
        assert row.months[Month.JANUARY] is None  # unknown stays unknown
        assert row.months.to_dict()[Month.JULY] == 100

        with pytest.raises(TypeError):
            row.months["jul"]  # type: ignore[index]
        with pytest.raises(ValueError):
            row.months[Month.JULY] = 200  # type: ignore[index]

    def test_accessor_is_monthaccessor(self):
        place = GeoPlaceFactory()
        row = GeoPlaceSeasonality.objects.create(geo_place=place)
        assert isinstance(row.months, MonthAccessor)

    def test_seasonality_write_via_schema_path(self):
        source = SourceInput(slug="wodore", source_id="season-hut-1")
        place, _status = GeoPlace.update_or_create(
            schema=_schema(
                [OperationInput(mode="mode.standard", capacity=40)],
                SeasonalityInput(months={7: 100, 12: 0}),
            ),
            from_source=source,
        )
        seasonality = place.seasonality  # type: ignore  # reverse OneToOne: plugin-less inference gap
        assert seasonality.months[Month.JULY] == 100
        assert seasonality.months[Month.DECEMBER] == 0
        assert seasonality.months[Month.JANUARY] is None


class TestWodoreSeasonalityImport:
    @pytest.fixture(autouse=True)
    def only_my_huts(self, hut_category: Category) -> None:
        Hut.objects.filter(is_active=True).update(is_active=False)
        # the reduced-without-type fallback resolves onto it
        Category.objects.get_or_create(
            slug="unknown",
            parent=hut_category.parent,
            defaults={"name": "Unbekannt"},
        )

    @staticmethod
    def _out() -> Any:
        import io

        return io.StringIO()

    def _place(self, hut: Hut) -> GeoPlace:
        return GeoPlace.objects.get(
            source_associations__organization__slug="wodore",
            source_associations__source_id=hut.slug,
        )

    def test_fuzzy_mapping_written(self, hut_category: Category):
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_closed=None,
            open_monthly={
                "month_07": "yes",
                "month_08": "yesish",
                "month_09": "maybe",
                "month_10": "noish",
                "month_11": "no",
                "month_12": "unknown",
            },
        )
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        seasonality = self._place(hut).seasonality  # type: ignore  # reverse OneToOne: plugin-less inference gap
        shares = seasonality.months.to_dict()
        assert shares[Month.JULY] == 100
        assert shares[Month.AUGUST] == 75
        assert shares[Month.SEPTEMBER] == 50
        assert shares[Month.OCTOBER] == 25
        assert shares[Month.NOVEMBER] == 0
        assert shares[Month.DECEMBER] is None  # unknown → NULL

    def test_below_100_without_reduced_type_resolves_unknown(
        self, hut_category: Category
    ):
        """PO-confirmed rule (design D4): months below 100 with no
        reduced type resolve the reduced mode to accommodation.unknown."""
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_open=None,
            capacity_closed=None,
            open_monthly={"month_12": "no"},
        )
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        place = self._place(hut)
        associations = {
            (a.category.slug, a.classifier.identifier)  # type: ignore[union-attr]
            for a in place.category_associations.all()  # type: ignore  # reverse FK: plugin-less inference gap
            if a.classifier_id
        }
        assert ("hut", "mode.standard") in associations
        assert ("unknown", "mode.reduced") in associations  # resolved
        operations = {
            o.mode.identifier: o.capacity
            for o in place.operations.all()  # type: ignore  # reverse FK: plugin-less inference gap
        }
        assert operations == {"mode.standard": None, "mode.reduced": None}

    def test_all_standard_months_no_reduced(self, hut_category: Category):
        """Months all 100 = always standard — no reduced mode appears."""
        hut = HutFactory(
            hut_type_open=hut_category,
            hut_type_closed=None,
            capacity_closed=None,
            open_monthly={f"month_{m:02d}": "yes" for m in range(1, 13)},
        )
        call_command("import_geoplaces", "-s", "wodore", stdout=self._out())

        place = self._place(hut)
        assert place.category_associations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap
        assert place.operations.count() == 1  # type: ignore  # reverse FK: plugin-less inference gap
