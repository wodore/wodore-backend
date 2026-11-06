"""Tests for Hut.create_from_schema with default-language (de) name sources.

Sources whose TranslationSchema carries German names (hhde, gipfelbuch,
sac, ...) crashed hut imports with modeltrans' "Attempted override of
'name' with 'name_de'": ``primary_name()`` sets the base ``name`` field
alongside the ``name_de`` virtual field, and modeltrans' patched
``Hut(...)`` init rejects that pair. The create path now drops the
default-language duplicate instead of aborting the whole import run.
"""

import pytest
from hut_services import (
    CapacitySchema,
    HutSchema,
    HutTypeSchema,
    OpenMonthlySchema,
    TranslationSchema,
)
from hut_services.core.schema.geo import LocationEleSchema

from server.apps.categories.models import Category
from server.apps.huts.models import Hut, HutTypeHelper

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _hut_type_categories():
    """Ensure the 'unknown' hut type category exists and is visible.

    In a fresh test DB the hut-type categories may not exist (the data
    migration depends on HutType rows) — same on-the-fly creation as the
    seed loader. The helper caches parent/values, so clear before/after.
    """
    # Map-tree aware (geoplace-category-tree): accommodation lives
    # under the amenity super-root; a parentless creation would be a
    # stray duplicate breaking HutTypeHelper's ambiguity-free lookup.
    parent = (
        Category.objects.filter(slug="accommodation", parent__slug="amenity").first()
        or Category.objects.filter(slug="accommodation", parent=None).first()
    )
    if parent is None:
        amenity = Category.objects.filter(slug="amenity", parent__slug="map").first()
        parent = Category.objects.create(
            slug="accommodation",
            name="Accommodation",
            is_active=True,
            parent=amenity,
        )
    if not Category.objects.filter(slug="unknown").exists():
        Category.objects.create(
            slug="unknown", name="Unknown", parent=parent, is_active=True
        )
    HutTypeHelper.clear_cache()
    # ``values``/``default_type`` are ``cachedclassproperty`` descriptors —
    # they cache under '_values_'/'_default_type_' on the class and
    # ``clear_cache()`` does not invalidate them; stale Category pks from a
    # rolled-back transaction then FK-violate the next test.
    for attr in ("_values_", "_default_type_"):
        if attr in vars(HutTypeHelper):
            delattr(HutTypeHelper, attr)
    yield
    HutTypeHelper.clear_cache()
    for attr in ("_values_", "_default_type_"):
        if attr in vars(HutTypeHelper):
            delattr(HutTypeHelper, attr)


def _schema(lon: float, **name_kwargs: str) -> HutSchema:
    return HutSchema(
        name=TranslationSchema(**name_kwargs),
        location=LocationEleSchema(lon=lon, lat=46.5, ele=2000),
        notes=[],
        capacity=CapacitySchema(),
        hut_type=HutTypeSchema(),
        open_monthly=OpenMonthlySchema(),
    )


class TestCreateFromSchemaDefaultLanguageNames:
    def test_german_name_creates_hut(self):
        hut = Hut.create_from_schema(
            hut_schema=_schema(8.51, de="Testhütte", en="Testhütte"), review=False
        )
        assert hut.pk is not None
        assert hut.name == "Testhütte"

    def test_german_only_name_creates_hut(self):
        hut = Hut.create_from_schema(
            hut_schema=_schema(8.52, de="Nur Deutsch"), review=False
        )
        assert hut.pk is not None
        assert hut.name == "Nur Deutsch"

    def test_non_default_language_name_still_works(self):
        hut = Hut.create_from_schema(
            hut_schema=_schema(8.53, fr="Refuge Test"), review=False
        )
        assert hut.pk is not None
        assert hut.name == "Refuge Test"
