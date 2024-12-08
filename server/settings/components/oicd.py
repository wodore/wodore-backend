"""
This file contains a definition for Content-Security-Policy headers.

Read more about it:
https://developer.mozilla.org/ru/docs/Web/HTTP/Headers/Content-Security-Policy

We are using `django-csp` to provide these headers.
Docs: https://github.com/mozilla/django-csp
"""

import dis
import requests
import os
import json
from server.settings.components import config
import logging


def discover_oidc(discovery_url: str) -> dict | None:
    """
    Performs OpenID Connect discovery to retrieve the provider configuration.
    """
    try:
        response = requests.get(discovery_url)
    except requests.exceptions.ConnectionError:
        logging.warning("Failed to retrieve provider configuration for '%s'.", discovery_url)
        return None
    if response.status_code != 200:
        logging.warning("Failed to retrieve provider configuration for '%s'.", discovery_url)
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
_ZITADEL_API_PRIVATE_KEY_JSON = (
    json.loads(str(config("ZITADEL_API_PRIVATE_KEY_JSON"))) if config("ZITADEL_API_PRIVATE_KEY_JSON", None) else {}
)
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
OIDC_OP_DISCOVERY_ENDPOINT = OIDC_OP_BASE_URL + "/.well-known/openid-configuration"

# Discover OpenID Connect endpoints
discovery_info = discover_oidc(OIDC_OP_DISCOVERY_ENDPOINT)
if discovery_info:
    OIDC_OP_AUTHORIZATION_ENDPOINT = discovery_info["authorization_endpoint"]
    OIDC_OP_TOKEN_ENDPOINT = discovery_info["token_endpoint"]
    OIDC_OP_USER_ENDPOINT = discovery_info["userinfo_endpoint"]
    OIDC_OP_JWKS_ENDPOINT = discovery_info["jwks_uri"]
    OIDC_OP_INTROSPECTION_ENDPOINT = discovery_info["introspection_endpoint"]

    _django_admin_url = config("DJANGO_ADMIN_URL") if config("DJANGO_ADMIN_URL", None) else "http://localhost:8000"
    LOGIN_REDIRECT_URL = f"{_django_admin_url}/admin"
    LOGOUT_REDIRECT_URL = f"{_django_admin_url}/admin"
    LOGIN_URL = f"{_django_admin_url}/oidc/authenticate/"

    ZITADEL_API_MACHINE_USERS = {
        us[0].strip(): us[1].strip()
        for us in [user_secret.split(":") for user_secret in config("ZITADEL_API_MACHINE_USERS", "").split(",")]
    }
