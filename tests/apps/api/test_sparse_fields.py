"""Sparse fieldsets (fields[TYPE]): parsing, projection, endpoint behavior."""

import pytest

from server.apps.api.query import (
    dump_sparse,
    dump_sparse_list,
    sparse_fields_query,
    sparse_include,
)
from server.apps.organizations.schema import OrganizationOptional

pytestmark = pytest.mark.django_db

OrgFields = sparse_fields_query(organizations=OrganizationOptional)


class OrgQuery(OrgFields):
    pass


class TestParsing:
    def test_bracket_keys_collected(self):
        q = OrgQuery.model_validate({"fields[organizations]": "slug,name"})
        assert q.fields == {"organizations": "slug,name"}

    def test_no_fields_gives_none(self):
        assert OrgQuery.model_validate({}).fields is None

    def test_unknown_type_is_400(self):
        from dmr import APIError

        with pytest.raises(APIError) as exc:
            OrgQuery.model_validate({"fields[nope]": "slug"})
        assert exc.value.raw_data["code"] == "validation_error"

    def test_legacy_include_is_400_validation_error(self):
        from dmr import APIError

        with pytest.raises(APIError) as exc:
            OrgQuery.model_validate({"include": "slug"})
        assert exc.value.raw_data["code"] == "validation_error"

    def test_legacy_exclude_is_400_validation_error(self):
        from dmr import APIError

        with pytest.raises(APIError) as exc:
            OrgQuery.model_validate({"exclude": "slug"})
        assert exc.value.raw_data["code"] == "validation_error"


class TestProjection:
    def test_default_include(self):
        q = OrgQuery.model_validate({})
        include = sparse_include(q, "organizations", default_include=["slug", "name"])
        assert {"slug", "name"} <= set(include)  # required name rides along

    def test_selection_plus_required(self):
        q = OrgQuery.model_validate({"fields[organizations]": "slug,url"})
        include = sparse_include(q, "organizations")
        assert {"slug", "url", "name"} <= set(include)  # name is required

    def test_all_keyword(self):
        q = OrgQuery.model_validate({"fields[organizations]": "__all__"})
        include = sparse_include(q, "organizations")
        assert set(OrganizationOptional.model_fields) <= set(include)

    def test_unknown_field_is_400(self):
        from dmr import APIError

        q = OrgQuery.model_validate({"fields[organizations]": "slug,nope"})
        with pytest.raises(APIError):
            sparse_include(q, "organizations")

    def test_nested_types_map_onto_dto_fields(self):
        from server.apps.huts.schemas import HutSchemaDetails

        HutFields = sparse_fields_query(
            huts=HutSchemaDetails,
            sources=HutSchemaDetails.model_fields["sources"].annotation,
        )

        class HQ(HutFields):
            pass

        q = HQ.model_validate(
            {"fields[huts]": "slug,sources", "fields[sources]": "slug,name"}
        )
        include = sparse_include(q, "huts")
        assert isinstance(include, dict)
        assert include["slug"] is ...
        assert include["sources"] == {"slug", "name"}


class TestDump:
    def test_dump_respects_selection(self):
        class Obj:
            slug = "sac"
            name = "SAC"
            url = "https://x"

        q = OrgQuery.model_validate({"fields[organizations]": "slug"})
        data = dump_sparse(OrganizationOptional, Obj(), q, "organizations")
        assert "slug" in data
        assert "url" not in data

    def test_dump_list_default(self):
        class Obj:
            slug = "sac"
            name = "SAC"

        q = OrgQuery.model_validate({})
        out = dump_sparse_list(
            OrganizationOptional, [Obj()], q, "organizations", default_include=["slug"]
        )
        assert out and "slug" in out[0]


class TestEndpoints:
    def test_organizations_fields_narrows(self, seed_data, client):
        listed = client.get("/v1/organizations/").json()
        assert listed, "seed data missing"
        response = client.get("/v1/organizations/", {"fields[organizations]": "slug"})
        assert response.status_code == 200
        first = response.json()[0]
        assert set(first) <= {"slug", "name", "slug_i18n", "name_i18n"}

    def test_organizations_detail_all(self, seed_data, client):
        listed = client.get("/v1/organizations/").json()
        slug = listed[0]["slug"]
        response = client.get(f"/v1/organizations/{slug}")
        assert response.status_code == 200
        assert len(response.json()) > 5  # __all__ default

    def test_include_parameter_removed(self, seed_data, client):
        response = client.get("/v1/organizations/", {"include": "slug"})
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"

    def test_exclude_parameter_removed(self, seed_data, client):
        response = client.get("/v1/organizations/", {"exclude": "slug"})
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    def test_unknown_type_on_endpoint(self, seed_data, client):
        response = client.get("/v1/organizations/", {"fields[huts]": "slug"})
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    def test_symbols_fields(self, seed_data, client):
        response = client.get("/v1/symbols/", {"fields[symbols]": "slug,style"})
        assert response.status_code == 200
        if response.json():
            assert set(response.json()[0]) <= {"slug", "style", "slug_i18n"}

    def test_hut_detail_nested_sources(self, seed_data, client):
        from server.apps.huts.models import Hut

        hut = Hut.objects.filter(is_active=True, is_public=True).first()
        assert hut is not None
        response = client.get(
            f"/v1/huts/{hut.slug}",
            {"fields[huts]": "slug,sources", "fields[sources]": "slug"},
        )
        assert response.status_code == 200, response.content[:300]
        data = response.json()
        assert "slug" in data
        if data.get("sources"):
            assert set(data["sources"][0]) <= {"slug"}


class TestSchema:
    def test_snapshot_has_deepobject_and_no_legacy(self):
        import json
        from pathlib import Path

        snapshot = json.loads(
            (
                Path(__file__).parents[3]
                / "server/apps/apiversions/openapi/2026-10-02.json"
            ).read_text()
        )
        seen_fields = 0
        for methods in snapshot["paths"].values():
            for op in methods.values():
                if not isinstance(op, dict):
                    continue
                for prm in op.get("parameters", []):
                    assert prm["name"] not in ("include", "exclude")
                    if prm["name"] == "fields":
                        seen_fields += 1
                        assert prm["style"] == "deepObject"
                        assert prm["explode"] is True
        assert seen_fields >= 7

    def test_new_version_registered(self):
        from server.apps.apiversions import registry

        assert "unreleased" in registry.versions()
        assert registry.current_version() == "unreleased"
