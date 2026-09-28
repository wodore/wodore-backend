"""Auth provider settings: Zitadel RP (default in production) and the
built-in provider (django-oauth-toolkit + django-allauth).

The switch is a single environment variable, ``AUTH_PROVIDER``:

- ``zitadel`` (default outside development/test): the classic relying-party
  surface - mozilla-django-oidc login (``/oidc/``), admin login redirect,
  SessionRefresh, the Zitadel ``PermissionBackend`` and token validation
  via introspection. A failed discovery fetch aborts startup (fail-fast).
- ``builtin`` (default in development/test): DOT serves the OIDC provider
  at ``/oauth/local/`` with django-allauth accounts behind it; tokens
  validate locally (opaque DB lookup / JWT signature + exact issuer).

The production default stays ``zitadel`` until the built-in flow has been
rehearsed in staging; the later flip is an env change
(``AUTH_PROVIDER=builtin``), not a deploy.

- ``ZITADEL_ROLLBACK_ENABLED``: while ``AUTH_PROVIDER=builtin`` and legacy
  Zitadel tokens may still be in circulation, the introspection validator
  stays available alongside the built-in one. Defaults to true outside
  development/test; removed together with the Zitadel decommission.
"""

import json
import logging
import re
from urllib.parse import urlparse

import requests
from authlib.jose import JsonWebKey

from django.core.exceptions import ImproperlyConfigured

from server.settings.components import config

_ENV = config("DJANGO_ENV", "development")
_IS_DEV_OR_TEST = _ENV in ("development", "test")

# --- Provider switch -----------------------------------------------------------

AUTH_PROVIDER = (
    config("AUTH_PROVIDER", default="builtin" if _IS_DEV_OR_TEST else "zitadel")
    .strip()
    .lower()
)
if AUTH_PROVIDER not in ("builtin", "zitadel", "none"):
    raise ImproperlyConfigured(
        f"AUTH_PROVIDER must be 'builtin', 'zitadel' or 'none', got '{AUTH_PROVIDER}'."
    )

# "none" disables every provider surface (no discovery fetch, no signing
# key) - the state image builds and "no auth" test runs want.
OIDC_ENABLED = AUTH_PROVIDER == "builtin"  # built-in provider surface
ZITADEL_RP_ENABLED = AUTH_PROVIDER == "zitadel"  # Zitadel RP surface

ZITADEL_ROLLBACK_ENABLED = config(
    "ZITADEL_ROLLBACK_ENABLED", cast=bool, default=not _IS_DEV_OR_TEST
)
if AUTH_PROVIDER == "none":
    ZITADEL_ROLLBACK_ENABLED = False

# --- Built-in provider -----------------------------------------------------------

# Issuer base path - the frontend's issuer URL is ``{origin}/oauth/local``.
# Kept from the hand-rolled provider so frontend configs stay valid.
OIDC_PROVIDER_BASE_PATH = "oauth/local"

# The SPA's public PKCE client id (seeded by ``local_auth_users``).
LOCAL_AUTH_CLIENT_ID = config("LOCAL_AUTH_CLIENT_ID", "wodore-local-dev")

# Comma-separated exact redirect URIs for the SPA client.
LOCAL_AUTH_REDIRECT_URIS = config("LOCAL_AUTH_REDIRECT_URIS", "")

# Committed dev-only RSA key (JWK). Only ever the fallback in dev/test -
# ``AUTH_PROVIDER=builtin`` outside dev/test requires a real key.
_DEV_PRIVATE_JWK: dict = {
    "kty": "RSA",
    "kid": "wodore-local-dev-1",
    "alg": "RS256",
    "use": "sig",
    "n": "xKXrj0Y-YchAsxa9dTNtE2PTmk_LDoWUrbnx4wefsrSL7r85pm4iINYxCQxQhHreZiUoCGy8kYnzwhkHRf9MZPpkQjUsf4z6Ku1VLq88nHjf_mXdwjoY0qneL-97zTh0qIj4xTaAQ-3D9aRMkynxb84p_M30Bnw_5ojfg2wmi3zaCvnA-oUmuam5KAiOjEaqmXktfsqgE_MhKE2Z-Mxc_UxEM_3nalr4JRCxRZ5J9nJHOMQe2wAF28NzdV13h4EGk3ShBZMCB2p7oyulB9x3O7s-CGhbbtLv3OXtuQGFDS8cgFqeNHGe6SqItZMWN8N1Atq9lZiRVOyFRaj4EdkTww",
    "e": "AQAB",
    "d": "ArP4e8TZPlUsf9RcBfyPJG6Wrdl97t-q2QPOzYeWdt7gyNyBCYbHBPuHZgVGJWQI-DoiMDzKZMJoLYP-48PsGWaQXTvyNiNKca-cdaKmqyHwNkTRL7EbvpLjgSDXa006MUeHX91CwGxIFBwjifxQG3DShpfldvdbQNXNzgvSWyV1zsfwuF3hc4UluO5Ow7lKDXpG_3A4lnj9rKEbpJS0iNZHFcR7-L_xA6HDC_WBFyQHbcOLe7dAofM7_SjQLWAIXeijigVca1hdbusY-rAfJ0tq4jeEMilARweV3EVu87W2n5I3Q7ewi0uSIzT2aJinTbadTL8bi2JftKMjpmW9FQ",
    "p": "_plJNRLB0_6DqD8pjX3oKnok74hY_kUM9-8s3aGn6_qOklBGLwkhEKT5dGsDnb_l5M_no-AcGCaNAnrcclr4BslKK3o3SBNjGgtCeae_1nkWS8DDtwL9VOgEPtyHjwNi4CPIyCJJuCMdIycxcfHk8w-bgiOSWBF0TmgWzAZavaU",
    "q": "xbr8O63PBr2hhXL5hQCGELHfc1PUeOz_-tHv69b47c05534CJ7Zc-RlH4G6l7mLYwxcSZ5TloRxcZZgXZga6C-JR1USgIuZOrdDJIiczE3OG6iR6_LQscK0Fzil0EmpreNvVeH_c5eDHslkp6MqQbv7HlpClwZQCxkd4_NxBn0c",
    "dp": "H8oV-PmBmC3EVKKmVpNtBLjBmeMFcaI_j0me6YGAzRc47A335XGXXlOrDh06k1zdoKdQ_gZCm8Vcf_3FPsYbCAXkK--TrX02N49GWphWfLobzZOhHF3UMeDSfuLcTkAW_XOaY1rcp5BC2BvRsa-Jbcv6F9LHOBXd1thqWElG1T0",
    "dq": "BM_vMZiiUDyvQKsyrWz81k0t7gWdRzAlbrpLR4cc2dTD0wF7FfJXQuy9lhW7Thjzw5O9K-4wxIIHMaXI8_-36XAho7oe15qZUZuiOYWQtal7IBmxMJNF_ZwIZyMVIxmZ8gAPqvYZrzKQSaPn5DWB3GGxA9YTYqmyg5bbt_O4WSM",
    "qi": "z8erlHg5LuMg_eZkNIxxhR6tGCEzMmSVDS0P__EkzLnvl2BosoOXxbjXnHHN9HNQxb7Z3aNTUV4bNkt9gZy1h1FnptXW1HeXxDdeQAJhmDtWiWa6FWS_UlTJY2bqEwIpI41ZQEryI0YQ3ACAwXaY5KONOhz4xNEk-s7n9BIB0qc",
}


def _resolve_provider_jwk() -> dict:
    raw = config("LOCAL_AUTH_PRIVATE_KEY_JWK", "")
    if raw:
        try:
            jwk = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ImproperlyConfigured(
                f"LOCAL_AUTH_PRIVATE_KEY_JWK is not valid JSON: {exc}"
            ) from exc
        if not isinstance(jwk, dict) or "n" not in jwk or "d" not in jwk:
            raise ImproperlyConfigured(
                "LOCAL_AUTH_PRIVATE_KEY_JWK must be a private RSA JWK "
                "(object with 'n' and 'd' members)."
            )
        return jwk
    if _IS_DEV_OR_TEST:
        return dict(_DEV_PRIVATE_JWK)
    raise ImproperlyConfigured(
        "The built-in OIDC provider is enabled (AUTH_PROVIDER=builtin) but no "
        "signing key is configured. Set LOCAL_AUTH_PRIVATE_KEY_JWK (JSON JWK) "
        "- e.g. via Infisical. The committed dev key is only allowed in "
        "development/test."
    )


OIDC_PROVIDER_PRIVATE_JWK: dict = _resolve_provider_jwk() if OIDC_ENABLED else {}


def _jwk_to_pem(jwk: dict) -> str:
    key = JsonWebKey.import_key(jwk, {"kty": "RSA"})
    pem = key.as_pem(is_private=True)  # pyright: ignore[reportAttributeAccessIssue]  # authlib Key stubs lack as_pem
    return pem.decode() if isinstance(pem, bytes) else str(pem)


if OIDC_ENABLED:
    OAUTH2_PROVIDER: dict = {
        "OIDC_ENABLED": True,
        "OIDC_RSA_PRIVATE_KEY": _jwk_to_pem(OIDC_PROVIDER_PRIVATE_JWK),
        "OAUTH2_VALIDATOR_CLASS": (
            "server.apps.local_auth.validator.ProviderOAuth2Validator"
        ),
        # Accept the frontend's (Zitadel-era) roles scope plus the OIDC
        # basics; offline_access enables refresh tokens.
        "SCOPES": {
            "openid": "OpenID Connect",
            "profile": "Profile",
            "email": "Email",
            "offline_access": "Offline access (refresh tokens)",
            "urn:zitadel:iam:org:projects:roles": "Legacy Zitadel roles scope",
        },
        "PKCE_REQUIRED": True,
        "ROTATE_REFRESH_TOKEN": True,
        "REFRESH_TOKEN_REUSE_PROTECTION": True,
        "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
        "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60,
        "REQUEST_APPROVAL_PROMPT": "auto",
        "ALLOWED_REDIRECT_URI_SCHEMES": (
            ["http", "https"] if _IS_DEV_OR_TEST else ["https", "com.wodore.app"]
        ),
    }

# --- Zitadel RP + rollback window --------------------------------------------------

ZITADEL_PROJECT = config("ZITADEL_PROJECT", "")
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_CLIENT_ID = config("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = config("OIDC_RP_CLIENT_SECRET", "")
OIDC_RP_SCOPES = "openid email phone profile"
ZITADEL_OP_BASE_URL = config("OIDC_OP_BASE_URL", "https://notset")
ZITADEL_API_PRIVATE_KEY_FILE_PATH = config("ZITADEL_API_PRIVATE_KEY_FILE_PATH", "")

# Optional internal URL for OIDC requests (e.g., k8s service URL)
OIDC_ISSUER_INTERNAL_URL = config("OIDC_ISSUER_INTERNAL_URL", "")
OIDC_OP_DISCOVERY_ENDPOINT = ZITADEL_OP_BASE_URL + "/.well-known/openid-configuration"


def discover_oidc(discovery_url: str, internal_url: str = "") -> dict | None:
    """Fetch the provider's OIDC discovery document (endpoint URLs)."""
    headers: dict[str, str] = {}
    actual_url = discovery_url

    if internal_url:
        parsed_original = urlparse(discovery_url)
        parsed_internal = urlparse(internal_url)
        actual_url = discovery_url.replace(
            f"{parsed_original.scheme}://{parsed_original.netloc}",
            f"{parsed_internal.scheme}://{parsed_internal.netloc}",
        )
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
            response.status_code,
        )
        return None
    provider_config = response.json()
    return {
        "authorization_endpoint": provider_config["authorization_endpoint"],
        "token_endpoint": provider_config["token_endpoint"],
        "userinfo_endpoint": provider_config["userinfo_endpoint"],
        "introspection_endpoint": provider_config["introspection_endpoint"],
        "jwks_uri": provider_config["jwks_uri"],
    }


def _load_zitadel_private_key() -> dict:
    raw = config("ZITADEL_API_PRIVATE_KEY_JSON", None)
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
        return {
            "client_id": data["clientId"],
            "key_id": data["keyId"],
            "private_key": data["key"],
        }
    except (json.JSONDecodeError, KeyError):
        logging.warning("ZITADEL_API_PRIVATE_KEY_JSON is invalid - ignored.")
        return {}


ZITADEL_API_PRIVATE_KEY = _load_zitadel_private_key()

# OIDC session renewal (mozilla-django-oidc), Zitadel RP mode only.
OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS = 60 * 60 * 24  # 24 hours
OIDC_STORE_ACCESS_TOKEN = True
OIDC_STORE_ID_TOKEN = True
OIDC_EXEMPT_URLS = [
    re.compile(r"^/v\d+/.*"),  # Exempt all API routes (any version)
    "/static/",
    "/media/",
]

discovery_info = None
if ZITADEL_RP_ENABLED:
    discovery_info = discover_oidc(OIDC_OP_DISCOVERY_ENDPOINT, OIDC_ISSUER_INTERNAL_URL)
    if discovery_info is None:
        raise ImproperlyConfigured(
            f"AUTH_PROVIDER=zitadel but the discovery document could not be "
            f"retrieved from '{OIDC_OP_DISCOVERY_ENDPOINT}'. Check that the "
            f"OIDC provider is reachable and OIDC_OP_BASE_URL is correct."
        )

if discovery_info:
    OIDC_OP_AUTHORIZATION_ENDPOINT = discovery_info["authorization_endpoint"]
    OIDC_OP_TOKEN_ENDPOINT = discovery_info["token_endpoint"]
    OIDC_OP_USER_ENDPOINT = discovery_info["userinfo_endpoint"]
    OIDC_OP_JWKS_ENDPOINT = discovery_info["jwks_uri"]

    _django_admin_url = (
        config("DJANGO_ADMIN_URL")
        if config("DJANGO_ADMIN_URL", None)
        else "http://localhost:8000"
    )
    LOGIN_REDIRECT_URL = f"{_django_admin_url}/admin"
    LOGIN_URL = "/oidc/authenticate/"

    ZITADEL_API_MACHINE_USERS = {
        us[0].strip(): us[1].strip()
        for us in (
            user_secret.split(":")
            for user_secret in config("ZITADEL_API_MACHINE_USERS", "").split(",")
        )
    }

# Introspection endpoint for the Zitadel token validators: explicit env,
# else from discovery (RP mode), else derived from the base URL (rollback).
ZITADEL_INTROSPECTION_URL = config("ZITADEL_INTROSPECTION_URL", "")
if not ZITADEL_INTROSPECTION_URL and discovery_info:
    ZITADEL_INTROSPECTION_URL = discovery_info["introspection_endpoint"]
if not ZITADEL_INTROSPECTION_URL:
    ZITADEL_INTROSPECTION_URL = ZITADEL_OP_BASE_URL.rstrip("/") + "/oauth/v2/introspect"

_ZITADEL_VALIDATION_ACTIVE = ZITADEL_RP_ENABLED or ZITADEL_ROLLBACK_ENABLED
if _ZITADEL_VALIDATION_ACTIVE and not ZITADEL_API_PRIVATE_KEY:
    if not _IS_DEV_OR_TEST:
        raise ImproperlyConfigured(
            "Zitadel token validation is active (AUTH_PROVIDER=zitadel or "
            "ZITADEL_ROLLBACK_ENABLED=true) but no Zitadel machine-user key "
            "is configured. Set ZITADEL_API_PRIVATE_KEY_JSON (or the "
            "_FILE_PATH variant), or set ZITADEL_ROLLBACK_ENABLED=false."
        )
