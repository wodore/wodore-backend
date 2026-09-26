"""Integration tests for the built-in OIDC provider (spec: oidc-provider).

Drives the flow the frontend's ``oidc-client-ts`` uses: discovery ->
authorize (allauth login redirect) -> token (PKCE S256) -> userinfo,
plus refresh-token rotation with reuse protection, the dev/test password
grant, JWKS and the end-session compatibility view.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db

REDIRECT_URI = "http://testserver/auth/signin-callback"
CLIENT_ID = "wodore-local-dev"
SCOPE = "openid profile email offline_access urn:zitadel:iam:org:projects:roles"
LEGACY_ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _authorize_params(challenge: str, **overrides: str) -> dict[str, str]:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": "some-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(overrides)
    return params


def _query_params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


@pytest.fixture(scope="module")
def local_users(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("local_auth_users")
    yield


@pytest.fixture
def logged_in_client(client, local_users):
    """Django test client with an authenticated admin session."""
    admin = get_user_model().objects.get(username="admin@local.test")
    client.force_login(admin)
    return client


class TestDiscovery:
    def test_frontend_compatible_discovery(self, client, local_users):
        response = client.get("/oauth/local/.well-known/openid-configuration")
        assert response.status_code == 200
        doc = response.json()
        assert doc["issuer"].endswith("/oauth/local")
        for key in (
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "jwks_uri",
        ):
            assert doc[key].startswith(doc["issuer"]), key
        assert "code" in doc["response_types_supported"]
        assert "S256" in doc["code_challenge_methods_supported"]
        # The legacy Zitadel roles scope must stay acceptable.
        assert "urn:zitadel:iam:org:projects:roles" in doc.get("scopes_supported", [])

    def test_jwks_publishes_provider_key(self, client, local_users):
        response = client.get("/oauth/local/.well-known/jwks.json")
        assert response.status_code == 200
        keys = response.json()["keys"]
        assert len(keys) >= 1


class TestAuthorizationCodeFlow:
    def test_unauthenticated_authorize_redirects_to_login(self, client, local_users):
        _, challenge = _pkce()
        response = client.get("/oauth/local/authorize/", _authorize_params(challenge))
        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith("/accounts/login/")
        # The authorize request is preserved for the post-login redirect.
        assert "next=" in location

    def test_full_pkce_flow(self, logged_in_client, local_users):
        client = logged_in_client
        verifier, challenge = _pkce()
        response = client.get("/oauth/local/authorize/", _authorize_params(challenge))
        assert response.status_code == 302
        query = _query_params(response["Location"])
        assert query["state"] == "some-state"
        code = query["code"]

        response = client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200
        token = response.json()
        assert token["token_type"] == "Bearer"
        assert token["expires_in"] > 0
        assert token["access_token"]
        assert token["id_token"]

        response = client.get(
            "/oauth/local/userinfo/",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        assert response.status_code == 200
        claims = response.json()
        assert claims["email"] == "admin@local.test"
        assert set(claims[LEGACY_ROLES_CLAIM]) == {"admin", "editor"}
        assert set(claims["roles"]) == {"group:admin", "group:editor"}
        assert "picture" in claims

    def test_code_is_single_use(self, logged_in_client, local_users):
        client = logged_in_client
        verifier, challenge = _pkce()
        response = client.get("/oauth/local/authorize/", _authorize_params(challenge))
        code = _query_params(response["Location"])["code"]
        exchange = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
        assert client.post("/oauth/local/token/", data=exchange).status_code == 200
        again = client.post("/oauth/local/token/", data=exchange)
        assert again.status_code == 400
        assert again.json()["error"] == "invalid_grant"

    def test_wrong_verifier_rejected(self, logged_in_client, local_users):
        client = logged_in_client
        _, challenge = _pkce()
        response = client.get("/oauth/local/authorize/", _authorize_params(challenge))
        code = _query_params(response["Location"])["code"]
        response = client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": "wrong-verifier",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_missing_pkce_rejected(self, logged_in_client, local_users):
        client = logged_in_client
        params = _authorize_params("")
        params.pop("code_challenge")
        params.pop("code_challenge_method")
        response = client.get("/oauth/local/authorize/", params)
        # PKCE is required: the authorize request itself must fail.
        assert response.status_code in (302, 400)
        if response.status_code == 302:
            assert "error" in _query_params(response["Location"])

    def test_redirect_uri_mismatch_rejected(self, logged_in_client, local_users):
        client = logged_in_client
        _, challenge = _pkce()
        params = _authorize_params(
            challenge, redirect_uri="https://evil.example/callback"
        )
        response = client.get("/oauth/local/authorize/", params)
        assert response.status_code in (302, 400)
        if response.status_code == 302:
            query = _query_params(response["Location"])
            assert "code" not in query


class TestRefreshRotation:
    @pytest.fixture
    def tokens(self, logged_in_client, local_users):
        client = logged_in_client
        verifier, challenge = _pkce()
        response = client.get("/oauth/local/authorize/", _authorize_params(challenge))
        code = _query_params(response["Location"])["code"]
        response = client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200
        return response.json()

    def test_refresh_rotates(self, logged_in_client, tokens):
        response = logged_in_client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            },
        )
        assert response.status_code == 200
        new = response.json()
        assert new["access_token"]
        assert new["refresh_token"]
        assert new["refresh_token"] != tokens["refresh_token"]

    def test_replayed_refresh_token_rejected(self, logged_in_client, tokens):
        first = logged_in_client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            },
        )
        assert first.status_code == 200
        second = logged_in_client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            },
        )
        assert second.status_code == 400
        assert second.json()["error"] == "invalid_grant"


class TestPasswordGrant:
    def test_valid_credentials(self, client, local_users):
        response = client.post(
            "/oauth/local/token/",
            data={
                "grant_type": "password",
                "username": "admin@local.test",
                "password": "admin-dev",
                "client_id": "wodore-local-dev-password",
                "client_secret": "wodore-local-dev-secret",
            },
        )
        assert response.status_code == 200
        assert response.json()["access_token"]


class TestUserinfo:
    def test_requires_bearer(self, client, local_users):
        response = client.get("/oauth/local/userinfo/")
        assert response.status_code == 401

    def test_rejects_garbage_token(self, client, local_users):
        response = client.get(
            "/oauth/local/userinfo/",
            headers={"Authorization": "Bearer not-a-token"},
        )
        assert response.status_code == 401


class TestLoginMethods:
    """The unified login page supports password, emailed one-time code and
    passkeys - email-only identifier, no username, no social, no phone."""

    def test_login_page_renders(self, client, local_users):
        response = client.get("/accounts/login/")
        assert response.status_code == 200

    def test_login_form_post_logs_in(self, client, local_users):
        """Drives the real allauth login form (GET + POST with credentials) -
        guards against configuration errors that only surface on POST
        (e.g. malformed ACCOUNT_RATE_LIMITS raising ValueError)."""
        from django.contrib.auth import get_user_model

        page = client.get("/accounts/login/")
        assert page.status_code == 200
        response = client.post(
            "/accounts/login/",
            data={"login": "admin@local.test", "password": "admin-dev"},
        )
        assert response.status_code == 302, getattr(response, "context", None)
        user = get_user_model().objects.get(username="admin@local.test")
        assert user.is_authenticated

    def test_login_form_rejects_wrong_password(self, client, local_users):
        response = client.post(
            "/accounts/login/",
            data={"login": "admin@local.test", "password": "wrong"},
        )
        assert response.status_code == 200  # form re-rendered with errors

    def test_email_only_identifier(self, settings):
        assert settings.ACCOUNT_LOGIN_METHODS == {
            "username": False,
            "email": True,
        }

    def test_one_time_code_login_enabled(self, settings):
        assert settings.ACCOUNT_LOGIN_BY_CODE_ENABLED is True

    def test_passkey_and_totp_mfa_enabled(self, settings):
        assert settings.MFA_PASSKEY_LOGIN_ENABLED is True
        assert set(settings.MFA_SUPPORTED_TYPES) == {
            "totp",
            "webauthn",
            "recovery_codes",
        }


class TestEndSession:
    def test_end_session_logs_out(self, logged_in_client, local_users):
        response = logged_in_client.get(
            "/oauth/local/end_session",
            {"post_logout_redirect_uri": "http://testserver/"},
        )
        assert response.status_code == 302
        assert response["Location"] == "http://testserver/"
        # session is gone -> next authorize redirects to login
        _, challenge = _pkce()
        response = logged_in_client.get(
            "/oauth/local/authorize/", _authorize_params(challenge)
        )
        assert response.status_code == 302
        assert response["Location"].startswith("/accounts/login/")
