"""JWT issuance/verification for the local dev/test auth provider.

Tokens are RS256 JWTs signed with a dev-only key. By default a committed
keypair is used - acceptable because the provider cannot run outside
DEBUG/test environments (see ``LOCAL_AUTH_ENABLED`` in
``server/settings/components/oidc.py``). Override with the
``LOCAL_AUTH_PRIVATE_KEY_JWK`` environment variable (JSON JWK) if needed.
"""

import hashlib
import json
import time
from math import floor
from typing import Any

from authlib.jose import JsonWebKey, jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured

# Committed dev-only RSA key (JWK). Never used in production - the provider is
# hard-gated to DEBUG/test environments.
_DEFAULT_PRIVATE_JWK: dict[str, Any] = {
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

ACCESS_TOKEN_LIFETIME = 3600
ID_TOKEN_LIFETIME = 300

_PRIVATE_KEY_MEMBERS = ("d", "p", "q", "dp", "dq", "qi")


def get_private_jwk() -> dict[str, Any]:
    raw = getattr(settings, "LOCAL_AUTH_PRIVATE_KEY_JWK", "") or ""
    if raw:
        try:
            return json.loads(raw)  # pyright: ignore[reportUnknownVariableType]
        except json.JSONDecodeError as exc:
            raise ImproperlyConfigured(
                f"LOCAL_AUTH_PRIVATE_KEY_JWK is not valid JSON: {exc}"
            ) from exc
    return dict(_DEFAULT_PRIVATE_JWK)


def get_public_jwk() -> dict[str, Any]:
    return {k: v for k, v in get_private_jwk().items() if k not in _PRIVATE_KEY_MEMBERS}


def _signing_key():
    return JsonWebKey.import_key(get_private_jwk(), {"kty": "RSA"})


def _verification_key():
    return JsonWebKey.import_key(get_public_jwk(), {"kty": "RSA"})


def _kid() -> str:
    return str(get_private_jwk().get("kid", "wodore-local-dev-1"))


def roles_claim(user: User) -> dict[str, dict[str, str]]:
    """Zitadel-shaped roles claim: a map keyed by role (group) names."""
    return {g.name: {} for g in user.groups.all()}


def _base_claims(
    issuer: str, user: User, audience: str, lifetime: int
) -> dict[str, Any]:
    now = floor(time.time())
    return {
        "iss": issuer,
        "sub": str(user.pk),
        "aud": audience,
        "iat": now,
        "exp": now + lifetime,
        "email": user.email,
        "name": user.get_full_name() or user.username,
    }


def issue_access_token(user: User, issuer: str, client_id: str) -> str:
    """Issue an RS256 access token including the roles claims for the API.

    The unqualified ``urn:zitadel:iam:org:project:roles`` claim is what the
    frontend store reads; the project-qualified variant is what the Zitadel
    introspection validator reads - the local validator accepts either.
    """
    claims: dict[str, Any] = _base_claims(
        issuer, user, client_id, ACCESS_TOKEN_LIFETIME
    )
    roles = roles_claim(user)
    claims["urn:zitadel:iam:org:project:roles"] = roles
    project = getattr(settings, "ZITADEL_PROJECT", "")
    if project:
        claims[f"urn:zitadel:iam:org:project:{project}:roles"] = roles
    header = {"alg": "RS256", "kid": _kid()}
    return _encode(header, claims)


def issue_id_token(user: User, issuer: str, client_id: str, nonce: str = "") -> str:
    claims: dict[str, Any] = _base_claims(issuer, user, client_id, ID_TOKEN_LIFETIME)
    claims["urn:zitadel:iam:org:project:roles"] = roles_claim(user)
    if nonce:
        claims["nonce"] = nonce
    header = {"alg": "RS256", "kid": _kid()}
    return _encode(header, claims)


def _encode(header: dict[str, Any], claims: dict[str, Any]) -> str:
    encoded = jwt.encode(header, claims, _signing_key())
    if isinstance(encoded, bytes):  # authlib returns bytes in some versions
        return encoded.decode()
    return str(encoded)


def gravatar_url(email: str) -> str:
    # Gravatar's URL scheme requires MD5. This is non-security identifier
    # hashing of a public email address - hence hashlib.new with
    # usedforsecurity=False (the documented constructor for non-security use).
    digest = hashlib.new(
        "md5", email.strip().lower().encode(), usedforsecurity=False
    ).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?d=identicon"


def verify_access_token(token: str) -> dict[str, Any]:
    """Verify signature and expiry of a local access token; return its claims.

    Raises ``ValueError`` on invalid/expired tokens.
    """
    try:
        claims = jwt.decode(
            token,
            _verification_key(),  # pyright: ignore[reportArgumentType]
        )
        exp = int(claims.get("exp", 0))
        if exp < floor(time.time()):
            raise ValueError("token expired")
        return dict(claims)  # pyright: ignore[reportUnknownArgumentType]
    except ValueError:
        raise
    except Exception as exc:  # authlib raises BadSignature/DecodeError subclasses
        raise ValueError(f"invalid token: {exc}") from exc
