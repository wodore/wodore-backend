"""Tests for the Zitadel-RP SessionRefresh scope and renewal redirect.

Regression (seen on https://hub.stg.wodore.com/): visiting the API host
root forwarded to Zitadel's login UI with a dead-end JSON error
("No active session found"). Two causes, both fixed here:

1. ``OIDC_EXEMPT_URLS`` only exempted ``/v1/*``, ``/static/`` and
   ``/media/`` - every other public path was SessionRefresh scope, so a
   stale admin session (live Django session, expired id_token) got
   silently dragged into the IdP flow on e.g. ``GET /``. The default is
   now inverted: only the admin surface is in scope.
2. On expiry the middleware sent the browser to the provider's
   authorization endpoint with ``prompt=none``. Zitadel Login V2 breaks
   the OIDC spec for that case without an IdP session
   (zitadel/zitadel#12165): it renders the broken error page instead of
   redirecting back with ``error=login_required``. The renewal now goes
   through the standard interactive ``/oidc/authenticate/`` entry point
   (seamless with a live IdP session, real login form without one).
"""

import time

import pytest

from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db

_MW = "server.middleware.oidc.AsyncSafeSessionRefresh"


@pytest.fixture
def rp_mode(settings):
    """Mount the Zitadel-RP middleware surface for the test.

    The middleware only runs in Zitadel-RP mode; the test env is builtin,
    so attach it (plus the endpoints its __init__/reverse() needs) via
    pytest-django's settings fixture. The OIDC backend must ALSO be in
    AUTHENTICATION_BACKENDS: django.contrib.auth.get_user() silently
    resolves an AnonymousUser for session backends that are not listed.
    """
    settings.MIDDLEWARE = (*settings.MIDDLEWARE, _MW)
    settings.ROOT_URLCONF = "tests.oidc_rp_urls"
    settings.AUTHENTICATION_BACKENDS = (
        *settings.AUTHENTICATION_BACKENDS,
        "mozilla_django_oidc.auth.OIDCAuthenticationBackend",
    )
    # SessionRefresh.__init__ and OIDCAuthenticationBackend.__init__
    # import the OP endpoints even though our redirect override no longer
    # uses the authorization endpoint (test env never runs discovery).
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://op.example.test/authorize"
    settings.OIDC_OP_TOKEN_ENDPOINT = "https://op.example.test/token"
    settings.OIDC_OP_USER_ENDPOINT = "https://op.example.test/userinfo"
    settings.OIDC_OP_JWKS_ENDPOINT = "https://op.example.test/.well-known/jwks.json"


@pytest.fixture
def oidc_session_user(client):
    """Logged-in user whose session was created by the OIDC backend."""
    user = get_user_model().objects.create_user(
        email="admin-session@example.test", password="x"
    )
    client.force_login(
        user, backend="mozilla_django_oidc.auth.OIDCAuthenticationBackend"
    )
    # force_login does not set an id_token expiry -> treated as expired,
    # i.e. the exact stale-session state that triggered the bug.
    return client, user


class TestSessionRefreshScope:
    """Only the admin surface may trigger a session renewal."""

    def test_public_root_with_expired_token_is_served(self, rp_mode, oidc_session_user):
        client, _ = oidc_session_user
        response = client.get("/")
        assert response.status_code == 200
        assert b"ok" in response.content

    @pytest.mark.parametrize(
        "path",
        ["/v1/huts/", "/robots.txt", "/llms.txt", "/health/", "/static/app.css"],
    )
    def test_public_paths_are_exempt(self, rp_mode, oidc_session_user, path):
        client, _ = oidc_session_user
        # The URLconf has no such routes: the assertion is that the
        # middleware does NOT redirect before routing (404, not 302).
        response = client.get(path)
        assert response.status_code == 404

    def test_anonymous_never_redirected(self, rp_mode, client):
        response = client.get("/admin/")
        assert response.status_code == 200

    def test_admin_with_valid_token_untouched(self, rp_mode, oidc_session_user):
        client, _ = oidc_session_user
        # NB: Client.session builds a NEW SessionStore per access - keep
        # one instance or the write and the save hit different stores.
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600
        session.save()
        response = client.get("/admin/")
        assert response.status_code == 200


class TestExpiredTokenRenewal:
    """Expired id_token -> interactive login entry point, not prompt=none."""

    def test_redirects_to_authenticate_with_next(self, rp_mode, oidc_session_user):
        client, _ = oidc_session_user
        response = client.get("/admin/")
        assert response.status_code == 302
        location = response["Location"]
        # Through our own interactive entry point (which keeps the IdP
        # request free of prompt=none), preserving the target via ?next=.
        assert location.startswith("/oidc/authenticate/")
        assert "next=%2Fadmin%2F" in location
        assert "op.example.test" not in location

    def test_xhr_gets_403_with_refresh_url(self, rp_mode, oidc_session_user):
        client, _ = oidc_session_user
        response = client.get("/admin/", headers={"x-requested-with": "XMLHttpRequest"})
        assert response.status_code == 403
        assert response["refresh_url"].startswith("/oidc/authenticate/")
