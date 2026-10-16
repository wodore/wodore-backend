"""RFC 9457 problem-details enrichment of the error contract (api-errors).

Covers the registry derivation (titles/type URIs/instance scoping), the
single-enrichment-point guarantee (dmr controllers, GeoJSON surfaces and
the version middleware all produce the enriched shape), and the
pinned-version behavior (additive only — nothing stripped).
"""

import pytest

from server.apps.api.error_codes import (
    INSTANCE_SCOPED_CODES,
    PROBLEM_TITLES,
    ErrorCode,
    enrich_problem_details,
    problem_fields,
    problem_instance,
    problem_type_uri,
)

pytestmark = pytest.mark.django_db

#: Members every enriched error body carries (RFC 9457).
ALWAYS_MEMBERS = ("type", "title", "status")


def assert_problem_members(body, *, status, code, instance=None):
    """Assert the full api-errors contract on an error body."""
    assert body["code"] == code  # preserved verbatim
    assert body["detail"]  # preserved verbatim
    assert body["status"] == status
    assert isinstance(body["status"], int)
    assert body["type"] == problem_type_uri(ErrorCode(code))
    assert body["title"] == PROBLEM_TITLES[ErrorCode(code)]
    if instance is None:
        assert "instance" not in body
    else:
        assert body["instance"] == instance


class TestProblemRegistry:
    """api-errors spec: registry completeness and derivation."""

    def test_every_code_has_title_and_type_uri(self):
        for code in ErrorCode:
            assert code in PROBLEM_TITLES
            uri = problem_type_uri(code)
            assert uri.endswith(f"/errors/{code.value}")
            assert uri.startswith(("http://", "https://"))

    def test_problem_fields_mirrors_status_as_int(self):
        members = problem_fields(ErrorCode.not_found, status=404)
        assert members["status"] == 404
        assert isinstance(members["status"], int)
        assert members["type"] == problem_type_uri(ErrorCode.not_found)
        assert "instance" not in members

    def test_problem_fields_includes_instance_when_given(self):
        members = problem_fields(
            ErrorCode.not_found, status=404, instance="/v1/huts/foo"
        )
        assert members["instance"] == "/v1/huts/foo"

    def test_instance_scoping(self):
        """Resource-scoped codes carry the path; the rest omit it."""
        assert INSTANCE_SCOPED_CODES == frozenset(
            (
                ErrorCode.not_found,
                ErrorCode.gone,
            )
        )
        assert problem_instance(ErrorCode.not_found, path="/x") == "/x"
        assert (
            enrich_problem_details(
                {"code": "not_found", "detail": "d"},
                status=404,
                path="/x",
            )["instance"]
            == "/x"
        )
        for code in ("validation_error", "throttled", "not_authenticated"):
            body = enrich_problem_details(
                {"code": code, "detail": "d"}, status=400, path="/x"
            )
            assert "instance" not in body

    def test_enrich_passes_non_contract_bodies_through(self):
        """Non-dicts, missing/unknown codes stay untouched (foreign payloads)."""
        for foreign in (
            "plain string",
            ["list"],
            {"no_code": 1},
            {"code": "not_a_wodore_code", "detail": "d"},
            {"code": 42},
        ):
            assert enrich_problem_details(foreign, status=400) == foreign

    def test_enrich_preserves_existing_members(self):
        original = {"code": "gone", "detail": "Sunset.", "extra": "kept"}
        enriched = enrich_problem_details(original, status=410, path="/v1/x")
        assert enriched["code"] == "gone"
        assert enriched["detail"] == "Sunset."
        assert enriched["extra"] == "kept"
        assert enriched["status"] == 410
        assert enriched["instance"] == "/v1/x"
        assert original == {"code": "gone", "detail": "Sunset.", "extra": "kept"}

    def test_registry_wins_over_preexisting_problem_members(self):
        """Review finding #9: the registry is the single source of truth.

        A body already carrying problem members (e.g. from an older
        enrichment layer) has them rewritten from the registry — never
        mixed-and-matched.
        """
        enriched = enrich_problem_details(
            {"code": "not_found", "detail": "d", "type": "about:blank"},
            status=404,
            path="/x",
        )
        assert enriched["type"] == problem_type_uri(ErrorCode.not_found)
        assert enriched["type"] != "about:blank"
        assert enriched["status"] == 404


class TestEndpointsShareEnrichment:
    """api-errors spec: shared machinery inheritance (dmr + GeoJSON)."""

    def test_hut_detail_404_carries_instance(self, seed_data, client):
        """Spec scenario: enriched not-found carries instance."""
        response = client.get("/v1/huts/does-not-exist")
        assert response.status_code == 404
        assert_problem_members(
            response.json(),
            status=404,
            code="not_found",
            instance="/v1/huts/does-not-exist",
        )

    def test_validation_error_400_omits_instance(self, seed_data, client):
        """Spec scenario: validation error shape."""
        response = client.get("/v1/organizations/", {"include": "slug"})
        assert response.status_code == 400
        assert_problem_members(response.json(), status=400, code="validation_error")

    def test_geojson_controller_validation_is_enriched(self, seed_data, client):
        """Spec scenario: GeoJSON endpoint inheritance (direct-write)."""
        response = client.get("/v1/huts/huts.geojson", {"bbox": "1,2,3"})
        assert response.status_code == 400
        assert_problem_members(response.json(), status=400, code="validation_error")

    def test_availability_404_is_enriched(self, seed_data, client):
        """raise_not_found from a plain availability handler."""
        response = client.get("/v1/huts/nope/availability/2026-01-01")
        assert response.status_code == 404
        assert_problem_members(
            response.json(),
            status=404,
            code="not_found",
            instance="/v1/huts/nope/availability/2026-01-01",
        )

    def test_method_not_allowed_405_is_enriched(self, seed_data, client):
        """Review finding #2: 405s must share the contract too.

        dmr's base ``handle_method_not_allowed`` bypasses ``to_error``;
        the ``ApiController`` override routes it back through it.
        """
        response = client.delete("/v1/huts/huts")
        assert response.status_code == 405
        assert response.headers["Allow"] == "GET"
        assert_problem_members(response.json(), status=405, code="validation_error")

    def test_openapi_error_schema_documents_problem_members(self, seed_data, client):
        """api-errors spec: OpenAPI error model documents the members."""
        schema = client.get("/v1/openapi.json").json()
        error_detail = schema["components"]["schemas"]["ErrorDetail"]
        documented = set(error_detail["properties"])
        assert documented >= {
            "code",
            "detail",
            "type",
            "title",
            "status",
            "instance",
        }


class TestPinnedVersionClients:
    """api-errors spec: enrichment applies to all versions, nothing stripped."""

    def test_pinned_client_receives_additive_fields(self, seed_data, client):
        pinned = "2026-10-02"
        response = client.get(
            "/v1/organizations/",
            {"include": "slug"},
            headers={"Api-Version": pinned},
        )
        assert response.status_code == 400
        assert_problem_members(response.json(), status=400, code="validation_error")

    def test_pinned_client_404_enriched(self, seed_data, client):
        response = client.get(
            "/v1/huts/does-not-exist", headers={"Api-Version": "2026-10-02"}
        )
        assert response.status_code == 404
        body = response.json()
        assert_problem_members(
            body,
            status=404,
            code="not_found",
            instance="/v1/huts/does-not-exist",
        )

    def test_endpoint_sunset_410_gone_is_enriched(self, seed_data, client, monkeypatch):
        """Review finding #4: ``gone`` is instance-scoped — a 410 from
        the endpoint-sunset guard carries ``instance``."""
        from datetime import date as date_cls

        from server.apps.apiversions import registry

        monkeypatch.setitem(
            registry.ENDPOINT_DEPRECATIONS,
            "get_hut_bookings",
            registry.EndpointDeprecation(
                announced=date_cls(2020, 1, 1),
                sunset=date_cls(2020, 7, 1),
                detail="gone",
            ),
        )
        response = client.get("/v1/huts/bookings", {"slugs": "nothing"})
        assert response.status_code == 410
        assert_problem_members(
            response.json(),
            status=410,
            code="gone",
            instance="/v1/huts/bookings",
        )

    def test_auth_401_is_enriched(self, settings):
        """Review finding #5: the auth handler's 401 body is enriched."""
        import json as _json

        from dmr import modify
        from dmr.test import DMRRequestFactory

        from server.apps.api.auth import AuthBearer
        from server.apps.api.controller import ApiController

        settings.OIDC_ENABLED = False
        settings.ZITADEL_RP_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False

        class ProbeController(ApiController):
            """Auth-not-configured probe (test_api_auth pattern)."""

            @modify(operation_id="probe_auth_401_enriched", auth=[AuthBearer()])
            def get(self) -> dict[str, bool]:
                """Probe endpoint."""

                return {"ok": True}

        response = DMRRequestFactory().get(
            "/probe", headers={"Authorization": "Bearer whatever"}
        )
        response = ProbeController.as_view()(response)
        assert response.status_code == 401
        assert_problem_members(
            _json.loads(response.content),
            status=401,
            code="not_authenticated",
        )


class TestVersionMiddlewareErrors:
    """api-errors spec: middleware version errors share the contract."""

    def test_header_query_conflict_is_enriched(self, seed_data, client):
        response = client.get(
            "/v1/huts/huts",
            {"api_version": "2098-01-01"},
            headers={"Api-Version": "2097-01-01"},
        )
        assert response.status_code == 400
        assert_problem_members(response.json(), status=400, code="validation_error")

    def test_unknown_version_is_enriched(self, seed_data, client):
        response = client.get("/v1/huts/huts", headers={"Api-Version": "not-a-date"})
        assert response.status_code == 400
        assert_problem_members(response.json(), status=400, code="validation_error")

    def test_sunset_version_is_enriched(self, seed_data, client):
        from datetime import date

        from server.apps.apiversions import registry

        change = registry.VersionChange(
            version="2020-01-01",
            description="test-only sunset version",
            deprecation_date=date(2020, 1, 1),
            sunset_date=date(2020, 7, 1),
        )
        registry.REGISTRY.append(change)
        try:
            response = client.get(
                "/v1/huts/huts", headers={"Api-Version": change.version}
            )
        finally:
            registry.REGISTRY.remove(change)
        assert response.status_code == 410
        assert_problem_members(response.json(), status=410, code="api_version_sunset")
