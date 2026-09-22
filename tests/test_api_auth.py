"""End-to-end tests for API bearer validation routing (spec: api-token-validation).

Uses a test-only Ninja API with AuthBearer-protected endpoints driven by
tokens from the local provider (password grant), covering success, wrong-role
401, invalid-token 401, disabled-mode 401, and validator routing per mode.
"""

import pytest
from ninja import NinjaAPI
from ninja.testing import TestClient

from django.test import Client

from server.apps.api.auth import AuthBearer, LocalJWTValidator

pytestmark = pytest.mark.django_db

api = NinjaAPI(urls_namespace="test-auth-api")


@api.get("/public", auth=None)
def public(request):
    return {"ok": True}


# NOTE: with the preserved Zitadel validation semantics, a requirement of
# ``roles=[...]`` only rejects when ``groups=[...]`` is also given and neither
# matches (see BaseTokenValidator.validate_token). Endpoints below therefore
# use the roles+groups combination, like the real (commented) booking usage.
@api.get("/admin-only", auth=AuthBearer(roles=["admin"], groups=["admin"]))
def admin_only(request):
    return {"ok": True}


@api.get("/editor-only", auth=AuthBearer(roles=["editor"], groups=["editor"]))
def editor_only(request):
    return {"ok": True}


def _password_token(username: str, password: str) -> str:
    response = Client().post(
        "/oauth/local/token",
        data={"grant_type": "password", "username": username, "password": password},
    )
    assert response.status_code == 200, response.content
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def local_users(django_db_setup, django_db_blocker):
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("local_auth_users")
    yield


@pytest.fixture
def client(local_users):
    return TestClient(api)


class TestProtectedEndpoints:
    def test_public_endpoint_needs_no_token(self, client):
        assert client.get("/public").json() == {"ok": True}

    def test_admin_token_passes_admin_endpoint(self, client):
        token = _password_token("admin@local.test", "admin-dev")
        response = client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_editor_token_rejected_on_admin_endpoint(self, client):
        token = _password_token("editor@local.test", "editor-dev")
        response = client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    def test_any_valid_token_passes_roles_only_endpoint(self, client):
        # Documented semantics quirk: without a groups requirement the roles
        # check cannot reject (groups=None always satisfies).
        other_api = NinjaAPI(urls_namespace="test-roles-only-api")

        @other_api.get("/roles-only", auth=AuthBearer(roles=["admin"]))
        def roles_only(request):
            return {"ok": True}

        token = _password_token("editor@local.test", "editor-dev")
        response = TestClient(other_api).get(
            "/roles-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_editor_token_passes_editor_endpoint(self, client):
        token = _password_token("editor@local.test", "editor-dev")
        response = client.get(
            "/editor-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_garbage_token_rejected(self, client):
        response = client.get(
            "/admin-only", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    def test_missing_token_rejected(self, client):
        response = client.get("/admin-only")
        assert response.status_code == 401


class TestDisabledMode:
    def test_clean_401_when_nothing_configured(self, settings):
        # NOTE: do NOT request real tokens while LOCAL_AUTH_ENABLED is
        # overridden to False: the provider routes are mounted at urlconf
        # import time behind that flag, and pytest-django may reload the
        # urlconf around the override - poisoning the rest of the run with
        # 404s. The "not configured" 401 fires before any token validation,
        # so a dummy token is sufficient (and keeps this test DB-free).
        settings.OIDC_ENABLED = False
        settings.LOCAL_AUTH_ENABLED = False
        # Endpoint built after the override, so its AuthBearer has no validator.
        disabled_api = NinjaAPI(urls_namespace="test-disabled-api")

        @disabled_api.get("/x", auth=AuthBearer())
        def x(request):
            return {"ok": True}

        response = TestClient(disabled_api).get(
            "/x", headers={"Authorization": "Bearer any-token"}
        )
        assert response.status_code == 401
        assert "not configured" in str(response.json()).lower()


class TestValidatorRouting:
    def test_local_mode_selects_local_validator(self, settings):
        settings.OIDC_ENABLED = False
        settings.LOCAL_AUTH_ENABLED = True
        assert isinstance(AuthBearer().validator, LocalJWTValidator)

    def test_oidc_mode_selects_zitadel_validator(self, settings):
        from server.apps.api.auth import ZitadelIntrospectTokenValidator

        settings.OIDC_ENABLED = True
        settings.LOCAL_AUTH_ENABLED = False
        settings.ZITADEL_API_PRIVATE_KEY = {
            "client_id": "test",
            "key_id": "test",
            "private_key": "test",
        }
        validator = AuthBearer().validator
        assert isinstance(validator, ZitadelIntrospectTokenValidator)

    def test_disabled_mode_has_no_validator(self, settings):
        settings.OIDC_ENABLED = False
        settings.LOCAL_AUTH_ENABLED = False
        assert AuthBearer().validator is None
