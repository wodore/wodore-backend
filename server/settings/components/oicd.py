"""
This file contains a definition for Content-Security-Policy headers.

Read more about it:
https://developer.mozilla.org/ru/docs/Web/HTTP/Headers/Content-Security-Policy

We are using `django-csp` to provide these headers.
Docs: https://github.com/mozilla/django-csp
"""

import requests
import os
from server.settings.components import config

def discover_oidc(discovery_url: str) -> dict:
    """
    Performs OpenID Connect discovery to retrieve the provider configuration.
    """
    response = requests.get(discovery_url)
    if response.status_code != 200:
        raise ValueError("Failed to retrieve provider configuration.")

    provider_config = response.json()

    # Extract endpoint URLs from provider configuration
    return {
        "authorization_endpoint": provider_config["authorization_endpoint"],
        "token_endpoint": provider_config["token_endpoint"],
        "userinfo_endpoint": provider_config["userinfo_endpoint"],
        "jwks_uri": provider_config["jwks_uri"],
    }


ZITADEL_PROJECT = config("ZITADEL_PROJECT")
OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID")
OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET")
OIDC_OP_BASE_URL = config("OIDC_OP_BASE_URL")

OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid email phone profile"
OIDC_OP_DISCOVERY_ENDPOINT = OIDC_OP_BASE_URL + "/.well-known/openid-configuration"

# Discover OpenID Connect endpoints
discovery_info = discover_oidc(OIDC_OP_DISCOVERY_ENDPOINT)
OIDC_OP_AUTHORIZATION_ENDPOINT = discovery_info["authorization_endpoint"]
OIDC_OP_TOKEN_ENDPOINT = discovery_info["token_endpoint"]
OIDC_OP_USER_ENDPOINT = discovery_info["userinfo_endpoint"]
OIDC_OP_JWKS_ENDPOINT = discovery_info["jwks_uri"]

LOGIN_REDIRECT_URL = "http://localhost:8000/"
LOGOUT_REDIRECT_URL = "http://localhost:8000/"
LOGIN_URL = "http://localhost:8000/oidc/authenticate/"
