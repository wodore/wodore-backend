"""HTTP-level tests for date-based API versioning (add-api-date-versioning).

Resolution, lifecycle, headers, exclusions, transforms (incl. the two
direct-write GeoJSON endpoints), ETag keying, version discovery and the
snapshot infrastructure.
"""

from datetime import date

import pytest

from server.apps.apiversions import registry
from server.apps.apiversions.transforms import each, feature_properties


@pytest.fixture
def pinned_old_version():
    """Test-only NEWER version with transforms, making the production
    versions 'old': clients pinned to them must receive downgraded shapes.
    """
    change = registry.VersionChange(
        version="zzzz-01-01",
        description="test-only: adds 'api_old_shape' marker on downgrade",
        responses={
            "get_huts": each(lambda hut: {**hut, "api_old_shape": True}),
            "get_huts_geojson": feature_properties(
                lambda props: {**props, "api_old_shape": True}
            ),
            "get_hut_availability_geojson": feature_properties(
                lambda props: {**props, "api_old_shape": True}
            ),
        },
    )
    registry.REGISTRY.append(change)
    try:
        yield change
    finally:
        registry.REGISTRY.remove(change)


@pytest.fixture
def deprecated_old_version():
    """Production versions + an old, deprecated-but-not-sunset version."""
    change = registry.VersionChange(
        version="2020-01-01",
        description="test-only deprecated version",
        deprecation_date=date(2026, 10, 1),
        sunset_date=date(2027, 4, 1),
    )
    registry.REGISTRY.append(change)
    try:
        yield change
    finally:
        registry.REGISTRY.remove(change)


@pytest.fixture
def sunset_old_version():
    """Production versions + a version whose sunset date has passed."""
    change = registry.VersionChange(
        version="2020-01-01",
        description="test-only sunset version",
        deprecation_date=date(2020, 1, 1),
        sunset_date=date(2020, 7, 1),
    )
    registry.REGISTRY.append(change)
    try:
        yield change
    finally:
        registry.REGISTRY.remove(change)


class TestVersionResolution:
    """api-versioning spec: Version selection."""

    @pytest.mark.django_db
    def test_no_version_serves_latest_with_echo(self, seed_data, client):
        response = client.get("/v1/huts/huts", {"limit": 1})
        assert response.status_code == 200
        assert response["Api-Version"] == registry.current_version()

    @pytest.mark.django_db
    def test_header_resolves_version(self, seed_data, client):
        version = registry.current_version()
        response = client.get(
            "/v1/huts/huts", {"limit": 1}, headers={"Api-Version": version}
        )
        assert response.status_code == 200
        assert response["Api-Version"] == version

    @pytest.mark.django_db
    def test_query_parameter_resolves_version(self, seed_data, client):
        version = registry.current_version()
        response = client.get("/v1/huts/huts", {"limit": 1, "api_version": version})
        assert response.status_code == 200
        assert response["Api-Version"] == version

    @pytest.mark.django_db
    def test_header_and_query_agree(self, seed_data, client):
        version = registry.current_version()
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1, "api_version": version},
            headers={"Api-Version": version},
        )
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_header_query_conflict_is_400(self, seed_data, client):
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1, "api_version": "2098-01-01"},
            headers={"Api-Version": "2097-01-01"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    @pytest.mark.django_db
    @pytest.mark.parametrize("raw", ["2099-13-01", "not-a-date", "2026-1-1"])
    def test_unknown_version_is_400(self, seed_data, client, raw):
        response = client.get(
            "/v1/huts/huts", {"limit": 1}, headers={"Api-Version": raw}
        )
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    @pytest.mark.django_db
    def test_version_not_in_registry_is_400(self, seed_data, client):
        response = client.get(
            "/v1/huts/huts", {"limit": 1}, headers={"Api-Version": "2025-01-01"}
        )
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


class TestVersioningScope:
    """api-versioning spec: Versioning scope."""

    @pytest.mark.django_db
    def test_svg_redirect_ignores_bogus_version(self, seed_data, client):
        response = client.get(
            "/v1/symbols/detailed/mountain.svg",
            headers={"Api-Version": "bogus"},
        )
        # Not a version error — the redirect (302) or its normal 404 both
        # prove no validation ran.
        assert response.status_code in {200, 301, 302, 404}
        assert "Api-Version" not in response.headers

    @pytest.mark.django_db
    def test_version_endpoint_ignores_bogus_version(self, seed_data, client):
        response = client.get("/v1/version", headers={"Api-Version": "bogus"})
        assert response.status_code == 200
        assert "Api-Version" not in response.headers

    @pytest.mark.django_db
    def test_schema_paths_validate_but_no_echo(self, seed_data, client):
        version = registry.current_version()
        response = client.get("/v1/openapi.json", {"api_version": version})
        assert response.status_code == 200
        assert "Api-Version" not in response.headers


class TestLifecycle:
    """api-versioning spec: Deprecation and sunset lifecycle."""

    @pytest.mark.django_db
    def test_deprecated_version_gets_headers(
        self, seed_data, client, deprecated_old_version
    ):
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1},
            headers={"Api-Version": deprecated_old_version.version},
        )
        assert response.status_code == 200
        assert response["Deprecation"].startswith("@")
        assert "Sunset" in response.headers
        assert 'rel="deprecation"' in response["Link"]

    @pytest.mark.django_db
    def test_sunset_version_is_410(self, seed_data, client, sunset_old_version):
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1},
            headers={"Api-Version": sunset_old_version.version},
        )
        assert response.status_code == 410
        body = response.json()
        assert body["code"] == "api_version_sunset"
        assert body["detail"]

    @pytest.mark.django_db
    def test_version_endpoint_reachable_for_sunset_versions(
        self, seed_data, client, sunset_old_version
    ):
        response = client.get("/v1/version")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_bookings_endpoints_announce_sunset(self, seed_data, client):
        response = client.get("/v1/huts/bookings", {"slugs": "nothing"})
        # The booking service is unavailable in tests (503) — the headers
        # prove the middleware wiring regardless of status.
        assert response.status_code in {200, 503}
        assert response["Deprecation"].startswith("@")
        assert "Sunset" in response.headers
        assert 'rel="deprecation"' in response["Link"]

    @pytest.mark.django_db
    def test_bookings_endpoints_410_after_sunset(self, seed_data, client, monkeypatch):
        from datetime import date as date_cls

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
        assert response.json()["code"] == "gone"


class TestBackwardTransforms:
    """api-versioning spec: Backward transforms (incl. direct-write ops)."""

    @pytest.mark.django_db
    def test_response_downgrade_regular_endpoint(
        self, seed_data, client, pinned_old_version
    ):
        old = max(v for v in registry.versions() if v != pinned_old_version.version)
        assert old != pinned_old_version.version
        response = client.get(
            "/v1/huts/huts", {"limit": 2}, headers={"Api-Version": old}
        )
        assert response.status_code == 200
        data = response.json()
        assert data and all(hut["api_old_shape"] is True for hut in data)
        # unpinned request gets the newest shape
        fresh = client.get("/v1/huts/huts", {"limit": 2})
        assert all("api_old_shape" not in hut for hut in fresh.json())

    @pytest.mark.django_db
    def test_response_downgrade_direct_write_geojson(
        self, seed_data, client, pinned_old_version
    ):
        old = max(v for v in registry.versions() if v != pinned_old_version.version)
        response = client.get("/v1/huts/huts.geojson", headers={"Api-Version": old})
        assert response.status_code == 200
        features = response.json()["features"]
        assert features
        assert all(f["properties"]["api_old_shape"] is True for f in features)
        fresh = client.get("/v1/huts/huts.geojson")
        assert all(
            "api_old_shape" not in f["properties"] for f in fresh.json()["features"]
        )

    @pytest.mark.django_db
    def test_response_downgrade_direct_write_availability_geojson(
        self, seed_data, client, pinned_old_version
    ):
        """The second direct-write endpoint (availability/{date}.geojson)
        must honor transforms — deleting the explicit helper call in
        server/apps/availability/api.py must fail this test (review P1)."""
        from tests.factories.availability import AvailabilityFactory

        from django.utils import timezone

        from server.apps.huts.models import Hut
        from server.apps.organizations.models import Organization

        hut = Hut.objects.first()
        org = Organization.objects.first()
        today = timezone.localdate()
        AvailabilityFactory(hut=hut, source_organization=org, availability_date=today)
        old = max(v for v in registry.versions() if v != pinned_old_version.version)
        response = client.get(
            f"/v1/huts/availability/{today.isoformat()}.geojson",
            headers={"Api-Version": old},
        )
        assert response.status_code == 200
        features = response.json()["features"]
        assert features, "availability fixture produced no features"
        assert all(f["properties"]["api_old_shape"] is True for f in features)

    def test_transform_helpers_defensive(self):
        from server.apps.apiversions.transforms import downgrade_response

        def downgrade_capacity(hut):
            """Defensive rename: only converts when the source key is
            present (design.md D4 rules)."""
            if "capacity_open" in hut:
                hut["capacity"] = hut.pop("capacity_open")
            return hut

        change = registry.VersionChange(
            version="zzzz-01-01",
            responses={"get_hut": downgrade_capacity},
        )
        registry.REGISTRY.append(change)
        try:
            # Field omitted via include/exclude → transform must not fail
            # nor add the field (defensive pop rules, design.md D4).
            out = downgrade_response("2026-10-01", "get_hut", {"slug": "x"})
            assert out == {"slug": "x"}
            # Field present → renamed exactly
            out = downgrade_response(
                "2026-10-01", "get_hut", {"slug": "x", "capacity_open": 42}
            )
            assert out == {"slug": "x", "capacity": 42}
        finally:
            registry.REGISTRY.remove(change)

    def test_changes_chain_in_reverse_order(self, pinned_old_version):
        from server.apps.apiversions.registry import changes_after

        ordered = [c.version for c in changes_after("2026-10-01")]
        assert ordered == sorted(ordered, reverse=True)
        assert pinned_old_version.version in ordered

    def test_request_upgrades_apply_oldest_to_newest(self):
        """upgrade_request chain order (deferred machinery, unit-pinned —
        review P2 test nit c)."""
        from server.apps.apiversions.transforms import upgrade_request

        first = registry.VersionChange(
            version="2098-01-01",
            requests={"get_hut": lambda d: {**d, "step": d.get("step", []) + ["2098"]}},
        )
        second = registry.VersionChange(
            version="zzzz-01-01",
            requests={"get_hut": lambda d: {**d, "step": d.get("step", []) + ["2099"]}},
        )
        registry.REGISTRY.extend([first, second])
        try:
            out = upgrade_request("2026-10-01", "get_hut", {"slug": "x"})
            assert out["step"] == ["2098", "2099"]  # oldest → newest
        finally:
            registry.REGISTRY.remove(first)
            registry.REGISTRY.remove(second)


class TestCaching:
    """api-versioning spec: Caching correctness."""

    @pytest.mark.django_db
    def test_vary_on_header_resolved_response(self, seed_data, client):
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1},
            headers={"Api-Version": registry.current_version()},
        )
        assert "Api-Version" in response["Vary"]

    @pytest.mark.django_db
    def test_vary_on_unpinned_response(self, seed_data, client):
        """Stored unpinned (current-version) responses must not be reused
        for later pinned requests on the same URL (review P2, RFC 9111)."""
        response = client.get("/v1/huts/huts", {"limit": 1})
        assert "Api-Version" in response.get("Vary", "")

    @pytest.mark.django_db
    def test_no_vary_on_query_resolved_response(self, seed_data, client):
        response = client.get(
            "/v1/huts/huts",
            {"limit": 1, "api_version": registry.current_version()},
        )
        # corsheaders may add its own Vary (Origin) — ours must not appear
        assert "Api-Version" not in response.get("Vary", "")

    @pytest.mark.django_db
    def test_etag_differs_across_versions(self, seed_data, client, pinned_old_version):
        old = max(v for v in registry.versions() if v != pinned_old_version.version)
        old_response = client.get("/v1/huts/huts.geojson", headers={"Api-Version": old})
        new_response = client.get("/v1/huts/huts.geojson")
        assert old_response.status_code == new_response.status_code == 200
        assert old_response["ETag"] != new_response["ETag"]

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "path,headers",
        [
            ("/v1/huts/huts", {"Api-Version": "bogus"}),  # 400 invalid
        ],
    )
    def test_error_responses_keep_cors_headers(self, seed_data, client, path, headers):
        """The middleware's 400/410 responses unwind through
        CorsMiddleware, so browser clients still see CORS headers
        (design.md D5.4 / review P2)."""
        from django.test import override_settings

        with override_settings(CORS_ALLOWED_ORIGINS=["https://app.example.com"]):
            response = client.get(
                path,
                {"limit": 1},
                headers={"Origin": "https://app.example.com", **headers},
            )
            assert response.status_code == 400
            assert response["Access-Control-Allow-Origin"] == (
                "https://app.example.com"
            )

    @pytest.mark.django_db
    def test_sunset_410_keeps_cors_headers(self, seed_data, client, sunset_old_version):
        from django.test import override_settings

        with override_settings(CORS_ALLOWED_ORIGINS=["https://app.example.com"]):
            response = client.get(
                "/v1/huts/huts",
                {"limit": 1},
                headers={
                    "Origin": "https://app.example.com",
                    "Api-Version": sunset_old_version.version,
                },
            )
            assert response.status_code == 410
            assert response["Access-Control-Allow-Origin"] == (
                "https://app.example.com"
            )


class TestVersionDiscovery:
    """api-versioning spec: Version discovery."""

    @pytest.mark.django_db
    def test_version_endpoint_has_api_block(self, seed_data, client):
        response = client.get("/v1/version")
        assert response.status_code == 200
        data = response.json()
        # Existing build fields unchanged
        for field in ("hash", "hash_long", "version", "timestamp", "environment"):
            assert field in data
        api = data["api"]
        assert api["current"] == registry.current_version()
        assert api["default"] == registry.default_version()
        entry = next(e for e in api["supported"] if e["version"] == api["current"])
        assert entry["status"] == "current"

    @pytest.mark.django_db
    def test_deprecated_version_listed_with_sunset(
        self, seed_data, client, deprecated_old_version
    ):
        data = client.get("/v1/version").json()
        entry = next(
            e
            for e in data["api"]["supported"]
            if e["version"] == deprecated_old_version.version
        )
        assert entry["status"] == "deprecated"
        assert entry["sunset"] == "2027-04-01"


class TestCors:
    """api-versioning spec: Cross-origin access to version headers."""

    @pytest.mark.django_db
    def test_preflight_allows_api_version_header(self, client):
        from django.test import override_settings

        with override_settings(CORS_ALLOWED_ORIGINS=["https://app.example.com"]):
            response = client.options(
                "/v1/huts/huts",
                headers={
                    "Origin": "https://app.example.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Api-Version",
                },
            )
            assert response.status_code == 200
            allowed = response["Access-Control-Allow-Headers"]
            assert "Api-Version" in allowed

    @pytest.mark.django_db
    def test_expose_headers_configured(self):
        from django.conf import settings

        assert "Api-Version" in settings.CORS_ALLOW_HEADERS
        for header in ("Api-Version", "Deprecation", "Sunset", "Link"):
            assert header in settings.CORS_EXPOSE_HEADERS


class TestRegistryIntegrity:
    """api-versioning spec: Registry integrity."""

    def test_bogus_operation_id_fails_check(self, monkeypatch):
        from server.apps.apiversions import checks as av_checks

        bogus = registry.VersionChange(
            version="zzzz-01-01",
            responses={"no_such_operation_xyz": lambda data: data},
        )
        monkeypatch.setattr(av_checks.registry, "REGISTRY", [bogus])
        errors = av_checks.check_registry_operation_ids()
        assert any(e.id == "apiversions.E001" for e in errors)

    def test_valid_registry_passes_check(self):
        from server.apps.apiversions import checks as av_checks

        assert av_checks.check_registry_operation_ids() == []

    def test_url_name_without_operation_id_fails_check(self, monkeypatch):
        """A route renamed without its @modify(operation_id=...) -> E003."""
        from server.apps.apiversions import checks as av_checks

        original = av_checks._collect_v1_url_names
        monkeypatch.setattr(
            av_checks,
            "_collect_v1_url_names",
            lambda: original() | {"renamed_endpoint"},
        )
        errors = av_checks.check_url_names_match_operation_ids()
        assert any(e.id == "apiversions.E003" for e in errors)

    def test_operation_id_without_url_name_fails_check(self, monkeypatch):
        """An operationId the resolver cannot produce -> versioning dead (E004)."""
        from server.apps.apiversions import checks as av_checks

        original = av_checks._collect_schema_operation_ids
        monkeypatch.setattr(
            av_checks,
            "_collect_schema_operation_ids",
            lambda: original() | {"ghost_operation"},
        )
        errors = av_checks.check_url_names_match_operation_ids()
        assert any(e.id == "apiversions.E004" for e in errors)

    def test_names_match_operation_ids_passes_check(self):
        """The invariant holds on the real wiring (hidden routes excluded)."""
        from server.apps.apiversions import checks as av_checks

        assert av_checks.check_url_names_match_operation_ids() == []

    def test_hidden_url_names_actually_hidden(self):
        """The HIDDEN_URL_NAMES allowlist must not rot: every entry is a
        real named /v1 route that is genuinely absent from the schema."""
        from server.apps.apiversions import checks as av_checks

        url_names = av_checks._collect_v1_url_names()
        schema_ids = av_checks._collect_schema_operation_ids()
        for name in av_checks.HIDDEN_URL_NAMES:
            assert name in url_names, f"{name} is not a route (remove it?)"
            assert name not in schema_ids, f"{name} IS documented (remove from hidden)"
