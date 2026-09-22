"""Integration tests for the local dev/test auth provider (spec: local-auth-provider).

Drives the exact flow the frontend's ``oidc-client-ts`` uses: discovery ->
authorize (popup login form + silent renew) -> token (PKCE S256) -> userinfo,
plus the password grant for tests/curl, JWKS verification and end-session.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db

REDIRECT_URI = "http://testserver/auth/signin-callback"
CLIENT_ID = "wodore-local-dev"


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
        "scope": "openid profile email urn:zitadel:iam:org:projects:roles",
        "state": "some-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(overrides)
    return params


def _query_params(location: str) -> dict[str, str]:
    parsed = urlparse(location)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


@pytest.fixture(scope="module")
def local_users(django_db_blocker):
    with django_db_blocker.unblock():
        call_command("local_auth_users")
    yield


@pytest.fixture
def admin_client(local_users, django_db_blocker):
    from django.contrib.auth.models import User
    from django.test import Client

    client = Client()
    with django_db_blocker.unblock():
        user = User.objects.get(username="admin@local.test")
        client.force_login(user)
    return client


class TestDiscovery:
    def test_frontend_compatible_discovery(self, client):
        response = client.get("/oauth/local/.well-known/openid-configuration")
        assert response.status_code == 200
        doc = response.json()
        assert doc["issuer"].endswith("/oauth/local")
        for key in (
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "jwks_uri",
            "end_session_endpoint",
        ):
            assert doc[key].startswith(doc["issuer"]), key
        assert "code" in doc["response_types_supported"]
        assert "S256" in doc["code_challenge_methods_supported"]
        assert "none" in doc["prompt_values_supported"]


class TestAuthorizationCodeFlow:
    def test_full_pkce_flow(self, client, local_users):
        verifier, challenge = _pkce()
        # 1. authorize -> login form
        response = client.get("/oauth/local/authorize", _authorize_params(challenge))
        assert response.status_code == 200
        assert b"local dev login" in response.content.lower()

        # 2. login POST -> redirect with code
        response = client.post(
            "/oauth/local/authorize",
            data={
                **_authorize_params(challenge),
                "username": "admin@local.test",
                "password": "admin-dev",
            },
        )
        assert response.status_code == 302
        query = _query_params(response["Location"])
        assert query["state"] == "some-state"
        code = query["code"]

        # 3. token exchange with PKCE verifier
        response = client.post(
            "/oauth/local/token",
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

        # 4. userinfo with the access token
        response = client.get(
            "/oauth/local/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        assert response.status_code == 200
        claims = response.json()
        assert claims["email"] == "admin@local.test"
        assert set(claims["urn:zitadel:iam:org:project:roles"]) == {"admin", "editor"}
        assert "picture" in claims

    def test_code_is_single_use(self, client, local_users):
        verifier, challenge = _pkce()
        response = client.post(
            "/oauth/local/authorize",
            data={
                **_authorize_params(challenge),
                "username": "admin@local.test",
                "password": "admin-dev",
            },
        )
        code = _query_params(response["Location"])["code"]
        exchange = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
        assert client.post("/oauth/local/token", data=exchange).status_code == 200
        again = client.post("/oauth/local/token", data=exchange)
        assert again.status_code == 400
        assert again.json()["error"] == "invalid_grant"

    def test_wrong_verifier_rejected(self, client, local_users):
        _, challenge = _pkce()
        response = client.post(
            "/oauth/local/authorize",
            data={
                **_authorize_params(challenge),
                "username": "admin@local.test",
                "password": "admin-dev",
            },
        )
        code = _query_params(response["Location"])["code"]
        response = client.post(
            "/oauth/local/token",
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

    def test_redirect_uri_mismatch_rejected(self, client, local_users):
        verifier, challenge = _pkce()
        response = client.post(
            "/oauth/local/authorize",
            data={
                **_authorize_params(challenge),
                "username": "admin@local.test",
                "password": "admin-dev",
            },
        )
        code = _query_params(response["Location"])["code"]
        response = client.post(
            "/oauth/local/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://evil.example/cb",
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 400

    def test_bad_credentials_rerenders_form(self, client, local_users):
        _, challenge = _pkce()
        response = client.post(
            "/oauth/local/authorize",
            data={
                **_authorize_params(challenge),
                "username": "admin@local.test",
                "password": "nope",
            },
        )
        assert response.status_code == 401
        assert b"Invalid credentials" in response.content


class TestSilentRenew:
    def test_prompt_none_without_session(self, client, local_users):
        _, challenge = _pkce()
        response = client.get(
            "/oauth/local/authorize", _authorize_params(challenge, prompt="none")
        )
        assert response.status_code == 302
        query = _query_params(response["Location"])
        assert query["error"] == "login_required"
        assert query["state"] == "some-state"

    def test_prompt_none_with_session(self, admin_client):
        _, challenge = _pkce()
        response = admin_client.get(
            "/oauth/local/authorize", _authorize_params(challenge, prompt="none")
        )
        assert response.status_code == 302
        query = _query_params(response["Location"])
        assert "code" in query

    def test_authenticated_user_skips_form(self, admin_client):
        _, challenge = _pkce()
        response = admin_client.get(
            "/oauth/local/authorize", _authorize_params(challenge)
        )
        assert response.status_code == 302
        assert "code" in _query_params(response["Location"])


class TestPasswordGrant:
    def test_valid_credentials(self, client, local_users):
        response = client.post(
            "/oauth/local/token",
            data={
                "grant_type": "password",
                "username": "editor@local.test",
                "password": "editor-dev",
            },
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_invalid_credentials(self, client, local_users):
        response = client.post(
            "/oauth/local/token",
            data={
                "grant_type": "password",
                "username": "editor@local.test",
                "password": "wrong",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_unsupported_grant_type(self, client):
        response = client.post(
            "/oauth/local/token", data={"grant_type": "client_credentials"}
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"


class TestJwksAndSession:
    def test_token_signature_verifies_against_jwks(self, client, local_users):
        from authlib.jose import JsonWebKey, jwt

        response = client.post(
            "/oauth/local/token",
            data={
                "grant_type": "password",
                "username": "admin@local.test",
                "password": "admin-dev",
            },
        )
        access_token = response.json()["access_token"]

        jwks = client.get("/oauth/local/jwks").json()
        assert jwks["keys"][0]["kty"] == "RSA"
        key = JsonWebKey.import_key(jwks["keys"][0], {"kty": "RSA"})
        claims = jwt.decode(
            access_token,
            key,  # pyright: ignore[reportArgumentType]
        )
        assert claims["sub"]
        assert claims["urn:zitadel:iam:org:project:roles"] == {
            "admin": {},
            "editor": {},
        }

    def test_userinfo_requires_bearer(self, client):
        response = client.get("/oauth/local/userinfo")
        assert response.status_code == 401

    def test_userinfo_rejects_garbage_token(self, client):
        response = client.get(
            "/oauth/local/userinfo", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    def test_end_session_logs_out(self, admin_client):
        response = admin_client.get(
            "/oauth/local/end_session",
            {"post_logout_redirect_uri": "http://testserver/"},
        )
        assert response.status_code == 302
        assert response["Location"] == "http://testserver/"
        # session is gone -> next authorize needs login again
        _, challenge = _pkce()
        response = admin_client.get(
            "/oauth/local/authorize", _authorize_params(challenge, prompt="none")
        )
        assert _query_params(response["Location"]).get("error") == "login_required"


class TestUsersCommand:
    def test_idempotent(self, db, django_db_blocker):
        from django.contrib.auth.models import User

        with django_db_blocker.unblock():
            call_command("local_auth_users")
            call_command("local_auth_users")
        admin = User.objects.get(username="admin@local.test")
        assert set(admin.groups.values_list("name", flat=True)) == {"admin", "editor"}
        assert User.objects.filter(username="editor@local.test").exists()
        assert User.objects.filter(username="admin@local.test").count() == 1
