"""End-to-end tests for API bearer validation routing (spec: api-token-validation).

Uses test-only dmr controllers with AuthBearer-protected endpoints driven
by tokens from the built-in provider (dev password grant), covering
success, wrong-role 401, invalid-token 401, disabled-mode 401, and
validator routing by issuer/flags.
"""

import pytest
from dmr import modify
from dmr.test import DMRRequestFactory

from django.test import Client

from server.apps.api.auth import (
    AuthBearer,
    BuiltInJWTValidator,
    ZitadelIntrospectTokenValidator,
)
from server.apps.api.controller import ApiController

pytestmark = pytest.mark.django_db


class PublicController(ApiController):
    """Unauthenticated probe endpoint."""

    @modify(operation_id="test_auth_public")
    def get(self) -> dict[str, bool]:
        """Public probe."""
        return {"ok": True}


class AdminOnlyController(ApiController):
    """Admin-role protected probe endpoint."""

    @modify(
        operation_id="test_auth_admin",
        auth=[AuthBearer(roles=["admin"], groups=["admin"])],
    )
    def get(self) -> dict[str, bool]:
        """Admin probe."""
        return {"ok": True}


class EditorOnlyController(ApiController):
    """Editor-role protected probe endpoint."""

    @modify(
        operation_id="test_auth_editor",
        auth=[AuthBearer(roles=["editor"], groups=["editor"])],
    )
    def get(self) -> dict[str, bool]:
        """Editor probe."""
        return {"ok": True}


# NOTE: with the preserved validation semantics, a requirement of
# ``roles=[...]`` only rejects when ``groups=[...]`` is also given and
# neither matches (see BaseTokenValidator.validate_requirements). The
# controllers above therefore use the roles+groups combination, like the
# real (commented) booking usage.


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
def rf(local_users):  # matches the usage below
    return DMRRequestFactory()


def _get(controller_cls, path, headers=None):
    request = DMRRequestFactory().get(path, headers=headers)
    return controller_cls.as_view()(request)


class TestProtectedEndpoints:
    def test_public_endpoint_needs_no_token(self, local_users):
        import json as _json

        response = _get(PublicController, "/public")
        assert response.status_code == 200
        assert _json.loads(response.content) == {"ok": True}

    def test_admin_token_passes_admin_endpoint(self, local_users):
        token = _password_token("admin@local.test", "admin-dev")
        response = _get(
            AdminOnlyController,
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_editor_token_rejected_on_admin_endpoint(self, local_users):
        token = _password_token("editor@local.test", "editor-dev")
        response = _get(
            AdminOnlyController,
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    def test_editor_token_passes_editor_endpoint(self, local_users):
        token = _password_token("editor@local.test", "editor-dev")
        response = _get(
            EditorOnlyController,
            "/editor-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_garbage_token_rejected(self, local_users):
        response = _get(
            AdminOnlyController,
            "/admin-only",
            headers={"Authorization": "Bearer not-a-token"},
        )
        assert response.status_code == 401

    def test_missing_token_rejected(self, local_users):
        response = _get(AdminOnlyController, "/admin-only")
        assert response.status_code == 401

    def test_wrong_issuer_jwt_rejected(self, local_users):
        from django.contrib.auth import get_user_model

        from server.apps.local_auth import tokens

        admin = get_user_model().objects.get(email="admin@local.test")
        forged = tokens.issue_access_token(
            admin, "https://evil.example/oauth/local", "wodore-local-dev"
        )
        response = _get(
            AdminOnlyController,
            "/admin-only",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert response.status_code == 401

    def test_revocation_takes_effect_immediately(self, local_users):
        from oauth2_provider.models import get_access_token_model

        token = _password_token("admin@local.test", "admin-dev")
        get_access_token_model().objects.filter(token=token).delete()
        response = _get(
            AdminOnlyController,
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


class TestDisabledMode:
    def test_clean_401_when_nothing_configured(self, local_users, settings):
        settings.OIDC_ENABLED = False
        settings.ZITADEL_RP_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False

        class DisabledController(ApiController):
            """Auth-not-configured probe."""

            @modify(operation_id="test_auth_disabled", auth=[AuthBearer()])
            def get(self) -> dict[str, bool]:
                """Disabled probe."""
                return {"ok": True}

        response = _get(
            DisabledController,
            "/x",
            headers={"Authorization": "Bearer whatever"},
        )
        assert response.status_code == 401
        import json as _json

        body = _json.loads(response.content)
        assert "not configured" in body["detail"].lower()


class TestValidatorRouting:
    def test_builtin_validator_selected_by_default(self, settings):
        settings.OIDC_ENABLED = True
        settings.ZITADEL_RP_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False
        validators = AuthBearer().validators
        assert [type(v) for v in validators] == [BuiltInJWTValidator]

    def test_zitadel_mode_selects_zitadel_validator(self, settings):
        settings.OIDC_ENABLED = False
        settings.ZITADEL_RP_ENABLED = True
        settings.ZITADEL_ROLLBACK_ENABLED = False
        settings.ZITADEL_API_PRIVATE_KEY = {
            "client_id": "test",
            "key_id": "test",
            "private_key": "test",
        }
        validators = AuthBearer().validators
        assert [type(v) for v in validators] == [ZitadelIntrospectTokenValidator]

    def test_rollback_adds_zitadel_validator(self, settings):
        settings.OIDC_ENABLED = True
        settings.ZITADEL_RP_ENABLED = False
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
        settings.ZITADEL_RP_ENABLED = False
        settings.ZITADEL_ROLLBACK_ENABLED = False
        assert AuthBearer().validators == []
