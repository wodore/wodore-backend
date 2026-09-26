"""Bearer token authentication for the Django Ninja API (spec: api-token-validation).

Validators share the scope/role/group matching logic from
``BaseTokenValidator``:

- ``BuiltInJWTValidator`` - verifies JWT access tokens issued by the built-in
  OIDC provider (django-oauth-toolkit) locally: RS256 signature against the
  provider key, expiry, issuer - no network call per request.
- ``ZitadelIntrospectTokenValidator`` - legacy rollback: verifies tokens
  issued by Zitadel via its introspection endpoint, available only while
  ``ZITADEL_ROLLBACK_ENABLED`` is true (until the Zitadel decommission).

``AuthBearer`` picks the active validators from settings per instance and
tries them in order. When auth is disabled, protected endpoints answer with
a clean 401 instead of crashing on missing provider settings.
"""

import json
import logging
import time
from math import floor
from typing import Any

import requests
from authlib.jose import jwt
from ninja.errors import HttpError
from ninja.security import HttpBearer

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    def __init__(self, error: dict[str, str], status_code: int):
        super().__init__()
        self.error = error
        self.status_code = status_code


class BaseTokenValidator:
    """Shared token validation: scope/role/group matching and error semantics.

    Roles and groups are read from the token's claims: the plain ``roles``
    claim where ``group:``-prefixed entries are groups and the rest are
    roles, with the legacy Zitadel claim keys still consulted for rollback
    tokens. ``_roles_claim_keys`` controls which claim names are consulted.
    """

    def __call__(
        self,
        token_string: str,
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    def _roles_claim_keys(self) -> tuple[str, ...]:
        project = getattr(settings, "ZITADEL_PROJECT", "")
        return (
            "roles",
            "urn:zitadel:iam:org:project:roles",
            f"urn:zitadel:iam:org:project:{project}:roles",
        )

    def _role_entries(self, token: dict[str, Any]) -> list[str]:
        entries: list[str] = []
        for key in self._roles_claim_keys():
            if not key:
                continue
            value = token.get(key)
            if isinstance(value, dict):
                # Map-shaped claims ({role: {}}) - legacy provider/userinfo
                # style; keys are the role names.
                entries.extend(value.keys())
            elif value:
                # List-shaped claims - the plain ``roles`` claim style.
                entries.extend(g for g in value if isinstance(g, str))
        return entries

    def match_token_scopes(
        self, token: dict[str, Any], or_scopes: list[str] | None
    ) -> bool:
        if or_scopes is None:
            return True
        scopes = token.get("scope", "").split()
        for and_scopes in or_scopes:
            if all(key in scopes for key in and_scopes.split()):
                return True
        return False

    def match_token_and_roles(
        self, token: dict[str, Any], and_roles: list[str] | None
    ) -> bool:
        if and_roles is None:
            return True
        roles = [g for g in self._role_entries(token) if "group:" not in g]
        return all(role in roles for role in and_roles)

    def match_token_groups(
        self, token: dict[str, Any], or_groups: list[str] | None
    ) -> bool:
        if or_groups is None:
            return True
        groups = [
            g.replace("group:", "") for g in self._role_entries(token) if "group:" in g
        ]
        return any(group in groups for group in or_groups)

    def validate_requirements(
        self,
        token: dict[str, Any],
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> None:
        now = floor(time.time())
        if not token:
            raise ValidatorError(
                {"code": "invalid_token_revoked", "description": "Token was revoked."},
                401,
            )
        if not token.get("active"):
            raise ValidatorError(
                {"code": "invalid_token_inactive", "description": "Token is inactive."},
                401,
            )
        if token["exp"] < now:
            raise ValidatorError(
                {"code": "invalid_token_expired", "description": "Token has expired."},
                401,
            )
        if not self.match_token_scopes(token, scopes):
            raise ValidatorError(
                {
                    "code": "insufficient_scope",
                    "description": f"Token has insufficient scope. Scopes required: {scopes}",
                },
                401,
            )
        if not self.match_token_and_roles(token, roles) and not self.match_token_groups(
            token, groups
        ):
            raise ValidatorError(
                {
                    "code": "insufficient_permission",
                    "description": f"Token has insufficient permission. Roles required: {roles} or group required: {groups}",
                },
                401,
            )


class BuiltInJWTValidator(BaseTokenValidator):
    """Verifies access tokens issued by the built-in OIDC provider (DOT).

    DOT 3.x issues opaque, database-backed access tokens; validation is a
    local primary-key lookup (no network call, instant revocation) with
    roles taken live from the user's Django groups. JWT-shaped tokens
    (e.g. minted by ``api_test_token``) verify locally via signature,
    expiry and issuer instead.
    """

    def _validate_opaque(self, token_string: str) -> dict[str, Any] | None:
        from oauth2_provider.models import get_access_token_model

        from server.apps.local_auth import tokens as provider_tokens

        try:
            access_token = (
                get_access_token_model()
                .objects.select_related("user", "application")
                .get(token=token_string)
            )
        except Exception:
            return None
        if access_token.expires is None or access_token.user is None:
            return None
        from django.utils import timezone

        if access_token.expires <= timezone.now():
            return None
        import datetime as _dt

        user = access_token.user
        return {
            "active": True,
            "exp": int(
                access_token.expires.replace(tzinfo=_dt.timezone.utc).timestamp()
                if access_token.expires.tzinfo is None
                else access_token.expires.timestamp()
            ),
            "scope": access_token.scope or "",
            "sub": str(user.pk),
            "claims": {"sub": str(user.pk)},
            provider_tokens.LEGACY_ROLES_CLAIM: provider_tokens.roles_claim(user),
            "roles": provider_tokens.plain_roles_claim(user),
        }

    def _validate_jwt(
        self, token_string: str, request: Any = None
    ) -> dict[str, Any] | None:
        from server.apps.local_auth import tokens as provider_tokens

        allowed = provider_tokens.default_allowed_issuers()
        if request is not None:
            base = getattr(settings, "OIDC_PROVIDER_BASE_PATH", "oauth/local").strip(
                "/"
            )
            try:
                allowed.append(request.build_absolute_uri(f"/{base}").rstrip("/"))
            except Exception:
                pass
        try:
            claims = provider_tokens.verify_access_token(token_string, allowed)
        except ValueError:
            return None
        scope = claims.get("scope", "")
        if isinstance(scope, (list, tuple)):
            scope = " ".join(str(s) for s in scope)
        token: dict[str, Any] = {
            "active": True,
            "exp": claims.get("exp", 0),
            "scope": scope,
            "sub": claims.get("sub"),
            "claims": claims,
        }
        for key in self._roles_claim_keys():
            if key in claims:
                token[key] = claims[key]
        return token

    def __call__(
        self,
        token_string: str,
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> dict[str, Any] | None:
        token = (
            self._validate_jwt(token_string, request)
            if token_string.count(".") == 2
            else self._validate_opaque(token_string)
        )
        if token is None:
            return None
        try:
            self.validate_requirements(token, scopes, roles, groups, request)
        except ValidatorError:
            return None
        return token


class ZitadelIntrospectTokenValidator(BaseTokenValidator):  # type: ignore[no-any-unimported]
    """Legacy rollback validator: Zitadel tokens via introspection.

    Active only while ``ZITADEL_ROLLBACK_ENABLED`` is true (default outside
    development/test); removed together with the Zitadel decommission.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.__api_private_key = (
            settings.ZITADEL_API_PRIVATE_KEY
            if settings.ZITADEL_API_PRIVATE_KEY
            else self._load_api_private_key_from_file(
                settings.ZITADEL_API_PRIVATE_KEY_FILE_PATH
            )
        )

    def _load_api_private_key_from_file(self, file_path: str) -> dict[str, str | None]:
        _key_obj: dict[str, str | None] = {}
        try:
            with open(file_path) as f:
                data = json.load(f)
                _key_obj["client_id"] = data["clientId"]
                _key_obj["key_id"] = data["keyId"]
                _key_obj["private_key"] = data["key"]
        except FileNotFoundError:
            if settings.DEBUG:
                logger.warning(
                    "ZITADEL_API_PRIVATE_KEY or _FILE_PATH not found. authentication does not work!!"
                )
                _key_obj["client_id"] = None
                _key_obj["key_id"] = None
                _key_obj["private_key"] = None
            else:
                raise ImproperlyConfigured(
                    "ZITADEL_API_PRIVATE_KEY or _FILE_PATH not found. Authentication cannot be configured."
                )

        return _key_obj

    def introspect_token(self, token_string: str) -> dict[str, Any]:
        # Create JWT for client assertion
        payload = {
            "iss": self.__api_private_key["client_id"],
            "sub": self.__api_private_key["client_id"],
            "aud": settings.ZITADEL_OP_BASE_URL,
            "exp": floor(time.time()) + 60 * 60,  # Expires in 1 hour
            "iat": floor(time.time()),
        }
        header = {
            "alg": settings.OIDC_RP_SIGN_ALGO,
            "kid": self.__api_private_key["key_id"],
        }
        jwt_token = jwt.encode(
            header,
            payload,
            self.__api_private_key["private_key"],
        )

        # Send introspection request
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": jwt_token,
            "token": token_string,
        }
        response = requests.post(
            settings.ZITADEL_INTROSPECTION_URL,
            headers=headers,
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data

    def __call__(
        self,
        token_string: str,
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> dict[str, Any] | None:
        token = self.introspect_token(token_string)
        try:
            self.validate_requirements(token, scopes, roles, groups, request)
        except ValidatorError:
            return None
        # TODO: return user with permission and groups
        return token


def _select_validators() -> list[BaseTokenValidator]:
    """Pick the active token validators from settings, in try-order."""
    validators: list[BaseTokenValidator] = []
    if settings.OIDC_ENABLED:
        validators.append(BuiltInJWTValidator())
    if settings.ZITADEL_ROLLBACK_ENABLED:
        validators.append(ZitadelIntrospectTokenValidator())
    return validators


class AuthBearer(HttpBearer):
    def __init__(
        self,
        scopes: list[str] | None = None,
        roles: list[str] | None = None,
        groups: list[str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.scopes = scopes
        self.roles = roles
        self.groups = groups
        self.validators = _select_validators()

    def authenticate(self, request: Any, token: str) -> dict[str, Any] | None:
        if not self.validators:
            raise HttpError(
                401,
                "Authentication is not configured on this server (OIDC is disabled).",
            )
        for validator in self.validators:
            result = validator(
                token_string=token,
                scopes=self.scopes,
                roles=self.roles,
                groups=self.groups,
                request=request,
            )
            if result is not None:
                return result
        return None
