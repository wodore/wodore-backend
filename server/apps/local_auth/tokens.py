"""JWT helpers for the built-in OIDC provider (spec: oidc-provider).

django-oauth-toolkit (DOT) is the token machinery; this module provides the
shared pieces around it:

- key resolution: the signing key comes from ``settings.OIDC_PROVIDER_PRIVATE_JWK``
  (env ``LOCAL_AUTH_PRIVATE_KEY_JWK``, Infisical-backed). In development/test
  a committed dev-only keypair is the fallback — production refuses to start
  without a real key (fail-fast in ``components/oidc.py``).
- claims shapes: the legacy Zitadel-shaped roles map the frontend reads and
  the plain ``roles`` list (``group:``-prefixed entries) the API validator
  reads — both built from Django groups.
- direct token minting/verification for the ``api_test_token`` command and
  the ``AuthBearer`` built-in validator (DOT access tokens are RS256 JWTs
  signed with the same key, verified the same way).
"""

import hashlib
import time
from math import floor
from typing import TYPE_CHECKING, Any

from authlib.jose import JsonWebKey, jwt

from django.conf import settings

if TYPE_CHECKING:
    from django.contrib.auth.models import User

ACCESS_TOKEN_LIFETIME = 3600
ID_TOKEN_LIFETIME = 300

LEGACY_ROLES_CLAIM = "urn:zitadel:iam:org:project:roles"


def _resolved_private_jwk() -> dict[str, Any]:
    jwk = getattr(settings, "OIDC_PROVIDER_PRIVATE_JWK", None)
    return dict(jwk) if jwk else {}


def _private_key_members() -> tuple[str, ...]:
    return ("d", "p", "q", "dp", "dq", "qi")


def get_private_jwk() -> dict[str, Any]:
    return _resolved_private_jwk()


def get_public_jwk() -> dict[str, Any]:
    private = get_private_jwk()
    return {k: v for k, v in private.items() if k not in _private_key_members()}


def _signing_key():
    return JsonWebKey.import_key(get_private_jwk(), {"kty": "RSA"})


def _verification_key():
    return JsonWebKey.import_key(get_public_jwk(), {"kty": "RSA"})


def _kid() -> str:
    return str(get_private_jwk().get("kid", "wodore-local-dev-1"))


def roles_claim(user: "User") -> dict[str, dict[str, str]]:
    """Legacy Zitadel-shaped roles claim: a map keyed by role (group) names."""
    return {g.name: {} for g in user.groups.all()}


def plain_roles_claim(user: "User") -> list[str]:
    """Plain ``roles`` claim (spec: oidc-provider): ``group:``-prefixed entries
    denote groups, all other entries denote roles."""
    return [f"group:{g.name}" for g in user.groups.all()]


def claims_for_user(user: "User") -> dict[str, Any]:
    """Shared claim set added to ID tokens, userinfo and JWT access tokens."""
    legacy = roles_claim(user)
    claims: dict[str, Any] = {
        "email": user.email,
        "name": user.get_full_name() or user.username,
        "picture": gravatar_url(user.email),
        LEGACY_ROLES_CLAIM: legacy,
        "roles": plain_roles_claim(user),
    }
    project = getattr(settings, "ZITADEL_PROJECT", "")
    if project:
        claims[f"urn:zitadel:iam:org:project:{project}:roles"] = legacy
    return claims


def _base_claims(
    issuer: str, user: "User", audience: str, lifetime: int
) -> dict[str, Any]:
    now = floor(time.time())
    return {
        "iss": issuer,
        "sub": str(user.pk),
        "aud": audience,
        "iat": now,
        "exp": now + lifetime,
    }


def issue_access_token(user: "User", issuer: str, client_id: str) -> str:
    """Mint an RS256 access token with the provider's claim shapes.

    Used by the ``api_test_token`` command; DOT issues its own JWTs for the
    real flows. Same key, same claims — the built-in validator accepts both.
    """
    claims: dict[str, Any] = _base_claims(
        issuer, user, client_id, ACCESS_TOKEN_LIFETIME
    )
    claims.update(claims_for_user(user))
    claims["scope"] = "openid profile email"
    claims["token_type"] = "Bearer"
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


def default_allowed_issuers() -> list[str]:
    """Configured extra issuer URLs accepted for built-in tokens
    (``LOCAL_AUTH_ALLOWED_ISSUERS``, comma-separated)."""
    from django.conf import settings

    raw = getattr(settings, "LOCAL_AUTH_ALLOWED_ISSUERS", "") or ""
    return [u.strip() for u in raw.split(",") if u.strip()]


def issuer_matches(iss: Any, allowed: list[str] | None = None) -> bool:
    """True if ``iss`` exactly matches an accepted issuer URL.

    Issuers are matched exactly (host + base path) - never by suffix - so a
    token from ``https://evil.example/oauth/local`` is rejected.
    """
    if not isinstance(iss, str) or not iss:
        return False
    candidates = set(allowed or [])
    base = getattr(settings, "OIDC_PROVIDER_BASE_PATH", "oauth/local").strip("/")
    for host in ("http://localhost:8000", "http://127.0.0.1:8000", "http://testserver"):
        candidates.add(f"{host}/{base}")
    return iss.rstrip("/") in candidates


def verify_access_token(
    token: str, allowed_issuers: list[str] | None = None
) -> dict[str, Any]:
    """Verify signature/expiry of a built-in provider access token; return claims.

    Raises ``ValueError`` on invalid, expired or wrong-issuer tokens.
    """
    try:
        claims = jwt.decode(
            token,
            _verification_key(),  # pyright: ignore[reportArgumentType]
        )
        exp = int(claims.get("exp", 0))
        if exp < floor(time.time()):
            raise ValueError("token expired")
        if not issuer_matches(claims.get("iss"), allowed_issuers):
            raise ValueError("token issuer is not the built-in provider")
        return dict(claims)  # pyright: ignore[reportUnknownArgumentType]
    except ValueError:
        raise
    except Exception as exc:  # authlib raises BadSignature/DecodeError subclasses
        raise ValueError(f"invalid token: {exc}") from exc
