"""Unit tests for pydantic→spec derivation (OpenSpec phase 1.3)."""

import pytest
from pydantic import BaseModel, Field

from django.contrib.gis.geos import Point
from django.db import connection
from django.test.utils import CaptureQueriesContext

from server.apps.api.readers import spec_from_schema
from server.apps.categories.models import Category
from server.apps.huts.models import Hut


def make_hut(**kwargs):
    """Create a minimal Hut (required fields: slug/name/description/
    country/location/hut_type_open)."""
    kwargs.setdefault("description", "")
    kwargs.setdefault("country_field", "CH")
    kwargs.setdefault("location", Point(8.5, 46.5))
    if "hut_type_open" not in kwargs:
        kwargs["hut_type_open"] = Category.objects.create(
            slug="spec-hut-type", identifier="spec-hut-type"
        )
    return Hut.objects.create(**kwargs)


class TypeRef(BaseModel):
    slug: str
    name: str


class ImageRef(BaseModel):
    id: int


class Flat(BaseModel):
    slug: str
    name: str
    is_active: bool


class WithFK(BaseModel):
    slug: str
    hut_type_open: TypeRef | None = None


class WithReverse(BaseModel):
    slug: str
    image_set: list[ImageRef]


class RelationAsScalar(BaseModel):
    slug: str
    hut_type_open: int


class WithComputed(BaseModel):
    slug: str
    distance: float


class TestSpecShape:
    def test_flat_schema_derives_field_entries(self):
        assert spec_from_schema(Hut, Flat) == [
            "slug",
            "name",
            "is_active",
            "i18n",
        ]  # i18n: modeltrans store, always kept

    def test_fk_nested_derives_prefetch_pair(self):
        spec = spec_from_schema(Hut, WithFK)
        assert spec[0] == "slug"
        assert spec[-1] == "i18n"
        entry = spec[1]
        assert isinstance(entry, dict)
        prepare, project = entry["hut_type_open"]
        assert callable(prepare) and callable(project)

    def test_sparse_selection_restricts_spec(self):
        spec = spec_from_schema(Hut, WithFK, fields={"slug", "hut_type_open"})
        assert spec[0] == "slug"
        assert "hut_type_open" in spec[1]
        assert spec[-1] == "i18n"

    def test_reverse_fk_nested_derives_relationship_entry(self):
        spec = spec_from_schema(Hut, WithReverse)
        assert spec == ["slug", {"image_set": ["id", "i18n"]}, "i18n"]

    def test_sparse_selection_drops_unselected_relations(self):
        spec = spec_from_schema(Hut, WithReverse, fields={"slug"})
        assert spec == ["slug", "i18n"]  # no relation entries at all

    def test_sparse_selection_matches_wire_alias(self):
        class Aliased(BaseModel):
            slug: str
            active: bool = Field(default=True, alias="is_active")

        spec = spec_from_schema(Hut, Aliased, fields={"slug", "is_active"})
        assert spec == ["slug", "active", "i18n"]

    def test_override_used_verbatim(self):
        def prepare(qs):
            return qs

        def project(obj):
            return obj.slug

        spec = spec_from_schema(
            Hut, WithComputed, overrides={"distance": (prepare, project)}
        )
        assert spec[:2] == ["slug", (prepare, project)]

    def test_relation_with_scalar_annotation_is_rejected(self):
        with pytest.raises(ValueError, match="relation needs a nested schema"):
            spec_from_schema(Hut, RelationAsScalar)

    def test_field_without_model_field_is_rejected(self):
        with pytest.raises(ValueError, match="no model field"):
            spec_from_schema(Hut, WithComputed)

    def test_error_lists_all_problem_fields(self):
        class TwoProblems(BaseModel):
            slug: str
            distance: float
            hut_type_open: int

        with pytest.raises(ValueError) as excinfo:
            spec_from_schema(Hut, TwoProblems)
        message = str(excinfo.value)
        assert "distance" in message
        assert "hut_type_open" in message


@pytest.mark.django_db
class TestProcessedQueryset:
    def test_prepare_selects_and_projects(self):
        from django_readers import specs

        prepare, project = specs.process(spec_from_schema(Hut, WithFK))
        make_hut(slug="spec-test", name="Spec Test")
        with CaptureQueriesContext(connection) as ctx:
            row = project(prepare(Hut.objects.filter(slug="spec-test")).get())
        # Two queries: base select + forward-FK prefetch (select_related
        # would be one, but collides with modeltrans' only()-rewriting).
        assert len(ctx) == 2
        assert row["slug"] == "spec-test"
        assert row["hut_type_open"]["slug"] == "spec-hut-type"

    def test_nullable_fk_does_not_n_plus_one(self):
        from django_readers import specs

        class WithClosed(BaseModel):
            slug: str
            hut_type_closed: TypeRef | None = None

        make_hut(slug="spec-test-null", name="Null FK", hut_type_closed=None)
        prepare, project = specs.process(spec_from_schema(Hut, WithClosed))
        with CaptureQueriesContext(connection) as ctx:
            row = project(prepare(Hut.objects.filter(slug="spec-test-null")).get())
        assert (
            len(ctx) == 1
        )  # base only: Django skips the prefetch query when the FK is NULL everywhere
        assert row["hut_type_closed"] is None

    def test_prepare_reverse_relation_prefetches(self):
        from django_readers import specs

        prepare, project = specs.process(spec_from_schema(Hut, WithReverse))
        make_hut(slug="spec-test-2", name="Spec Test 2")
        with CaptureQueriesContext(connection) as ctx:
            list(prepare(Hut.objects.filter(slug="spec-test-2")))
        # Two queries: base select + prefetch of the reverse relation.
        assert len(ctx) == 2

    def test_sparse_selection_issues_fewer_queries(self):
        from django_readers import specs

        prepare, _ = specs.process(spec_from_schema(Hut, WithReverse, fields={"slug"}))
        make_hut(slug="spec-test-3", name="Spec Test 3")
        with CaptureQueriesContext(connection) as ctx:
            list(prepare(Hut.objects.filter(slug="spec-test-3")))
        # No relation selected -> no prefetch query.
        assert len(ctx) == 1
