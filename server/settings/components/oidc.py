"""OIDC provider settings: the built-in provider (django-oauth-toolkit +
django-allauth) and the Zitadel rollback window.

- ``OIDC_ENABLED``: gates the built-in provider surface — DOT's OAuth2/OIDC
  endpoints under ``/oauth/local/``, allauth's account URLs, the admin login
  redirect — and the built-in JWT validator. Defaults to **true in all
  environments**; an explicit environment value always wins.
- ``ZITADEL_ROLLBACK_ENABLED``: while tokens issued by Zitadel may still be
  in circulation, the introspection validator stays available. Defaults to
  true outside development/test; explicit env value wins. Removed together
  with the Zitadel decommission.

The provider's signing key comes from ``LOCAL_AUTH_PRIVATE_KEY_JWK`` (JSON
JWK, Infisical-backed). In development/test a committed dev-only keypair is
the fallback; everywhere else startup aborts without a real key (fail-fast).
"""

import json
import logging

from authlib.jose import JsonWebKey

from django.core.exceptions import ImproperlyConfigured

from server.settings.components import config

_ENV = config("DJANGO_ENV", "development")
_IS_DEV_OR_TEST = _ENV in ("development", "test")

# --- Flags -------------------------------------------------------------------

OIDC_ENABLED = config("OIDC_ENABLED", cast=bool, default=True)

ZITADEL_ROLLBACK_ENABLED = config(
    "ZITADEL_ROLLBACK_ENABLED", cast=bool, default=not _IS_DEV_OR_TEST
)

# --- Built-in provider ---------------------------------------------------------

# Issuer base path — the frontend's issuer URL is ``{origin}/oauth/local``.
# Kept from the hand-rolled provider so frontend configs stay valid.
OIDC_PROVIDER_BASE_PATH = "oauth/local"

# The SPA's public PKCE client id (seeded by ``local_auth_users``).
LOCAL_AUTH_CLIENT_ID = config("LOCAL_AUTH_CLIENT_ID", "wodore-local-dev")

# Comma-separated exact redirect URIs for the SPA client.
LOCAL_AUTH_REDIRECT_URIS = config("LOCAL_AUTH_REDIRECT_URIS", "")

# Committed dev-only RSA key (JWK). Only ever the fallback in dev/test —
# production must provide ``LOCAL_AUTH_PRIVATE_KEY_JWK``.
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
        "The built-in OIDC provider is enabled (OIDC_ENABLED defaults to "
        "true) but no signing key is configured. Set LOCAL_AUTH_PRIVATE_KEY_JWK "
        "(JSON JWK) - e.g. via Infisical. The committed dev key is only "
        "allowed in development/test."
    )


OIDC_PROVIDER_PRIVATE_JWK: dict = _resolve_provider_jwk() if OIDC_ENABLED else {}


def _jwk_to_pem(jwk: dict) -> str:
    key = JsonWebKey.import_key(jwk, {"kty": "RSA"})
    pem = key.as_pem(is_private=True)
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

# --- Zitadel rollback window ---------------------------------------------------

# Legacy machine-user key for introspection client assertions (same format
# the Zitadel RP used). Only needed while ZITADEL_ROLLBACK_ENABLED is true.
ZITADEL_PROJECT = config("ZITADEL_PROJECT", "")
OIDC_RP_SIGN_ALGO = "RS256"
ZITADEL_OP_BASE_URL = config("OIDC_OP_BASE_URL", "https://notset")
ZITADEL_INTROSPECTION_URL = config(
    "ZITADEL_INTROSPECTION_URL",
    ZITADEL_OP_BASE_URL.rstrip("/") + "/oauth/v2/introspect",
)
ZITADEL_API_PRIVATE_KEY_FILE_PATH = config("ZITADEL_API_PRIVATE_KEY_FILE_PATH", "")


def _load_zitadel_private_key() -> dict:
    raw = config("ZITADEL_API_PRIVATE_KEY_JSON", None)
    if raw:
        try:
            data = json.loads(raw)
            return {
                "client_id": data["clientId"],
                "key_id": data["keyId"],
                "private_key": data["key"],
            }
        except (json.JSONDecodeError, KeyError) as exc:
            logging.warning(
                "ZITADEL_API_PRIVATE_KEY_JSON is invalid - ignored: %s", exc
            )
    return {}


ZITADEL_API_PRIVATE_KEY = _load_zitadel_private_key()

if ZITADEL_ROLLBACK_ENABLED and not ZITADEL_API_PRIVATE_KEY:
    if not _IS_DEV_OR_TEST:
        raise ImproperlyConfigured(
            "ZITADEL_ROLLBACK_ENABLED=true but no Zitadel machine-user key is "
            "configured. Set ZITADEL_API_PRIVATE_KEY_JSON (or the "
            "_FILE_PATH variant), or set ZITADEL_ROLLBACK_ENABLED=false."
        )
