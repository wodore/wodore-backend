"""End-to-end tests for API bearer validation routing (spec: api-token-validation).

Uses a test-only Ninja API with AuthBearer-protected endpoints driven by
tokens from the built-in provider (dev password grant), covering success,
wrong-role 401, invalid-token 401, disabled-mode 401, and validator
routing by issuer/flags.
"""

import pytest
from ninja import NinjaAPI
from ninja.testing import TestClient

from django.test import Client

from server.apps.api.auth import (
    AuthBearer,
    BuiltInJWTValidator,
    ZitadelIntrospectTokenValidator,
)

pytestmark = pytest.mark.django_db

api = NinjaAPI(urls_namespace="test-auth-api")


@api.get("/public", auth=None)
def public(request):
    return {"ok": True}


# NOTE: with the preserved validation semantics, a requirement of
# ``roles=[...]`` only rejects when ``groups=[...]`` is also given and neither
# matches (see BaseTokenValidator.validate_requirements). Endpoints below
# therefore use the roles+groups combination, like the real (commented)
# booking usage.
@api.get("/admin-only", auth=AuthBearer(roles=["admin"], groups=["admin"]))
def admin_only(request):
    return {"ok": True}


@api.get("/editor-only", auth=AuthBearer(roles=["editor"], groups=["editor"]))
def editor_only(request):
    return {"ok": True}


def _password_token(username: str, password: str) -> str:
    response = Client().post(
        "/oauth/local/token/",
        data={
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": "wodore-local-dev-password",
            "client_secret": "wodore-local-dev-secret",
        },
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

    def test_editor_token_passes_editor_endpoint(self, client):
        token = _password_token("editor@local.test", "editor-dev")
        response = client.get(
            "/editor-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    def test_garbage_token_rejected(self, client):
        response = client.get(
            "/admin-only", headers={"Authorization": "Bearer not-a-token"}
        )
        assert response.status_code == 401

    def test_missing_token_rejected(self, client):
        response = client.get("/admin-only")
        assert response.status_code == 401

    def test_wrong_issuer_jwt_rejected(self, client):
        from django.contrib.auth import get_user_model

        from server.apps.local_auth import tokens

        admin = get_user_model().objects.get(username="admin@local.test")
        forged = tokens.issue_access_token(
            admin, "https://evil.example/oauth/local", "wodore-local-dev"
        )
        response = client.get(
            "/admin-only", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    def test_revocation_takes_effect_immediately(self, client):
        from oauth2_provider.models import get_access_token_model

        token = _password_token("admin@local.test", "admin-dev")
        get_access_token_model().objects.filter(token=token).delete()
        response = client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401


class TestDisabledMode:
    def test_clean_401_when_nothing_configured(self, settings):
        settings.OIDC_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False
        disabled_api = NinjaAPI(urls_namespace="test-disabled-api")

        @disabled_api.get("/x", auth=AuthBearer())
        def x(request):
            return {"ok": True}

        response = TestClient(disabled_api).get(
            "/x", headers={"Authorization": "Bearer whatever"}
        )
        assert response.status_code == 401
        assert "not configured" in response.json()["detail"].lower()


class TestValidatorRouting:
    def test_builtin_validator_selected_by_default(self, settings):
        settings.OIDC_ENABLED = True
        settings.ZITADEL_ROLLBACK_ENABLED = False
        validators = AuthBearer().validators
        assert [type(v) for v in validators] == [BuiltInJWTValidator]

    def test_rollback_adds_zitadel_validator(self, settings):
        settings.OIDC_ENABLED = True
        settings.ZITADEL_ROLLBACK_ENABLED = True
        settings.ZITADEL_API_PRIVATE_KEY = {
            "client_id": "test",
            "key_id": "test",
            "private_key": "test",
        }
        validators = AuthBearer().validators
        assert [type(v) for v in validators] == [
            BuiltInJWTValidator,
            ZitadelIntrospectTokenValidator,
        ]

    def test_disabled_mode_has_no_validators(self, settings):
        settings.OIDC_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False
        assert AuthBearer().validators == []
