"""
This file contains the OIDC (Zitadel RP) settings and the local dev/test
auth provider flags.

- ``OIDC_ENABLED``: activates the Zitadel relying-party surface (discovery,
  ``/oidc/`` URLs, admin login redirect, PermissionBackend, SessionRefresh).
  Enabled by default in production/staging, disabled in development/test;
  an explicit environment value always wins. When enabled, a failed discovery
  fetch aborts startup (fail-fast).
- ``LOCAL_AUTH_ENABLED``: activates the built-in dev/test OIDC provider
  (``server.apps.local_auth``) so the frontend can authenticate directly
  against Django without Zitadel. Only ever active in development/test, and
  explicitly refused elsewhere.
"""

import json
import logging
import os
import re
from urllib.parse import urlparse

import requests

from django.core.exceptions import ImproperlyConfigured

from server.settings.components import config


def discover_oidc(discovery_url: str, internal_url: str = "") -> dict | None:
    """
    Performs OpenID Connect discovery to retrieve the provider configuration.

    Args:
        discovery_url: The public OIDC discovery URL
        internal_url: Optional internal URL to use instead (e.g., for k8s service)
    """
    headers = {}
    actual_url = discovery_url

    if internal_url:
        parsed_original = urlparse(discovery_url)
        parsed_internal = urlparse(internal_url)

        # Replace scheme and netloc with internal URL, keep path
        actual_url = discovery_url.replace(
            f"{parsed_original.scheme}://{parsed_original.netloc}",
            f"{parsed_internal.scheme}://{parsed_internal.netloc}",
        )

        # Add Host header with original hostname
        headers["Host"] = parsed_original.netloc

    try:
        response = requests.get(actual_url, headers=headers, timeout=10)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.MissingSchema,
    ) as e:
        logging.warning(
            "Failed to retrieve provider configuration for '%s': '%s'.",
            discovery_url,
            str(e),
        )
        return None
    if response.status_code != 200:
        logging.warning(
            "Failed to retrieve provider configuration for '%s' (Status code: %s).",
            discovery_url,
        )
        return None
        # raise ValueError("Failed to retrieve provider configuration.")
    provider_config = response.json()

    # Extract endpoint URLs from provider configuration
    return {
        "authorization_endpoint": provider_config["authorization_endpoint"],
        "token_endpoint": provider_config["token_endpoint"],
        "userinfo_endpoint": provider_config["userinfo_endpoint"],
        "introspection_endpoint": provider_config["introspection_endpoint"],
        "jwks_uri": provider_config["jwks_uri"],
    }


ZITADEL_PROJECT = config("ZITADEL_PROJECT", "")
OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET", "")
OIDC_OP_BASE_URL = config("OIDC_OP_BASE_URL", "https://notset")
ZITADEL_API_PRIVATE_KEY_FILE_PATH = config("ZITADEL_API_PRIVATE_KEY_FILE_PATH", "")


def _load_zitadel_private_key() -> dict:
    raw = config("ZITADEL_API_PRIVATE_KEY_JSON", None)
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        logging.warning("ZITADEL_API_PRIVATE_KEY_JSON is not valid JSON - ignored.")
        return {}


_ZITADEL_API_PRIVATE_KEY_JSON = _load_zitadel_private_key()
ZITADEL_API_PRIVATE_KEY = (
    {
        "client_id": _ZITADEL_API_PRIVATE_KEY_JSON["clientId"],
        "key_id": _ZITADEL_API_PRIVATE_KEY_JSON["keyId"],
        "private_key": _ZITADEL_API_PRIVATE_KEY_JSON["key"],
    }
    if _ZITADEL_API_PRIVATE_KEY_JSON
    else {}
)


OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid email phone profile"

# --- Feature flags ---------------------------------------------------------
# Components load before the environment files (which define DEBUG), so the
# defaults are derived from DJANGO_ENV - the same source DEBUG comes from
# (development.py sets DEBUG=True, everything else False).
_ENV = os.environ.get("DJANGO_ENV", "development")
_IS_DEV_OR_TEST = _ENV in ("development", "test")

OIDC_ENABLED = config("OIDC_ENABLED", cast=bool, default=not _IS_DEV_OR_TEST)

# Local dev/test auth provider: defaults to the inverse of OIDC in dev/test
# and is hard-guarded - enabling it elsewhere aborts startup.
LOCAL_AUTH_ENABLED = config(
    "LOCAL_AUTH_ENABLED", cast=bool, default=_IS_DEV_OR_TEST and not OIDC_ENABLED
)
if LOCAL_AUTH_ENABLED and not _IS_DEV_OR_TEST:
    raise ImproperlyConfigured(
        "LOCAL_AUTH_ENABLED=true is only allowed in development/test "
        "environments (DJANGO_ENV=development or DJANGO_ENV=test)."
    )

# Local provider configuration (only meaningful when LOCAL_AUTH_ENABLED).
# The client id the frontend sends; a public PKCE client without secret.
LOCAL_AUTH_CLIENT_ID = config("LOCAL_AUTH_CLIENT_ID", "wodore-local-dev")
# Optional override of the signing key (JSON JWK). Defaults to the committed
# dev-only keypair in server/apps/local_auth/tokens.py.
LOCAL_AUTH_PRIVATE_KEY_JWK = config("LOCAL_AUTH_PRIVATE_KEY_JWK", "")

# Optional internal URL for OIDC requests (e.g., k8s service URL)
OIDC_ISSUER_INTERNAL_URL = config("OIDC_ISSUER_INTERNAL_URL", "")
# Inert when OIDC is disabled; only fetched in the OIDC_ENABLED branch below.
OIDC_OP_DISCOVERY_ENDPOINT = OIDC_OP_BASE_URL + "/.well-known/openid-configuration"

# OIDC session renewal settings
# https://mozilla-django-oidc.readthedocs.io/en/stable/settings.html#oidc-renew-id-token-expiry-seconds
# Time before ID token expiration to trigger renewal (default: 15 minutes = 900 seconds)
# Set to 1 day to reduce frequent re-authentication
OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = 60 * 60 * 24  # 24 hours

# Whether to store access token and refresh token in session (default: True)
OIDC_STORE_ACCESS_TOKEN = True
OIDC_STORE_ID_TOKEN = True

# Exempt public API routes from SessionRefresh middleware
# This prevents the middleware from returning 403 errors on public endpoints
# when the user's OIDC session has expired. API endpoints can still be
# selectively protected using Django Ninja's auth=AuthBearer(...) decorator.
OIDC_EXEMPT_URLS = [
    re.compile(r"^/v\d+/.*"),  # Exempt all API routes (any version)
    "/static/",  # Exempt static files
    "/media/",  # Exempt media files (development only)
]

# Discover OpenID Connect endpoints. Only fetched when OIDC is enabled - and
# then failing fast on an unreachable provider instead of silently producing
# a broken admin login.
discovery_info = None
if OIDC_ENABLED:
    discovery_info = discover_oidc(OIDC_OP_DISCOVERY_ENDPOINT, OIDC_ISSUER_INTERNAL_URL)
    if discovery_info is None:
        raise ImproperlyConfigured(
            f"OIDC is enabled but the discovery document could not be "
            f"retrieved from '{OIDC_OP_DISCOVERY_ENDPOINT}'. Check that the "
            f"OIDC provider is reachable and OIDC_OP_BASE_URL is correct."
        )

if discovery_info:
    OIDC_OP_AUTHORIZATION_ENDPOINT = discovery_info["authorization_endpoint"]
    OIDC_OP_TOKEN_ENDPOINT = discovery_info["token_endpoint"]
    OIDC_OP_USER_ENDPOINT = discovery_info["userinfo_endpoint"]
    OIDC_OP_JWKS_ENDPOINT = discovery_info["jwks_uri"]
    OIDC_OP_INTROSPECTION_ENDPOINT = discovery_info["introspection_endpoint"]

    _django_admin_url = (
        config("DJANGO_ADMIN_URL")
        if config("DJANGO_ADMIN_URL", None)
        else "http://localhost:8000"
    )
    # Redirect to /admin after successful login
    LOGIN_REDIRECT_URL = f"{_django_admin_url}/admin"
    LOGOUT_REDIRECT_URL = (
        f"{_django_admin_url}/"  # Does not work, still goes to login page again
    )
    LOGIN_URL = f"{_django_admin_url}/oidc/authenticate/"

    ZITADEL_API_MACHINE_USERS = {
        us[0].strip(): us[1].strip()
        for us in [
            user_secret.split(":")
            for user_secret in config("ZITADEL_API_MACHINE_USERS", "").split(",")
        ]
    }
