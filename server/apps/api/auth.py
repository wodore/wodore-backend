"""Bearer token authentication for the Django Ninja API (spec: api-token-validation).

Two validators share the scope/role/group matching logic from
``BaseTokenValidator``:

- ``ZitadelIntrospectTokenValidator`` - OIDC mode (``OIDC_ENABLED``): verifies
  access tokens via the Zitadel introspection endpoint using a private-key
  JWT client assertion.
- ``LocalJWTValidator`` - local mode (``LOCAL_AUTH_ENABLED``): verifies JWTs
  issued by the built-in dev/test provider (``server.apps.local_auth``).

``AuthBearer`` picks the validator from settings per instance. When neither
mode is active, protected endpoints answer with a clean 401 instead of
crashing on missing provider settings.
"""

import json
import logging
import time
from math import floor
from typing import Any, Dict

import requests
from authlib.jose import jwt
from authlib.oauth2.rfc7662 import IntrospectTokenValidator
from ninja.errors import HttpError
from ninja.security import HttpBearer

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class ValidatorError(Exception):
    def __init__(self, error: Dict[str, str], status_code: int):
        super().__init__()
        self.error = error
        self.status_code = status_code


class BaseTokenValidator:
    """Shared token validation: scope/role/group matching and error semantics.

    Roles and groups are read from Zitadel-shaped claims (a list where
    ``group:``-prefixed entries are groups and the rest are roles).
    ``_roles_claim_keys`` controls which claim names are consulted.
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
        return (f"urn:zitadel:iam:org:project:{project}:roles",)

    def _role_entries(self, token: dict[str, Any]) -> list[str]:
        entries: list[str] = []
        for key in self._roles_claim_keys():
            value = token.get(key)
            if isinstance(value, dict):
                # Local tokens carry roles as {role: {}} (map, like Zitadel
                # userinfo); keys are the role names.
                entries.extend(value.keys())
            elif value:
                # Zitadel introspection carries roles as a flat list.
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


class ZitadelIntrospectTokenValidator(BaseTokenValidator, IntrospectTokenValidator):  # type: ignore[no-any-unimported]
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
            "aud": settings.OIDC_OP_BASE_URL,
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
            settings.OIDC_OP_INTROSPECTION_ENDPOINT,
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


class LocalJWTValidator(BaseTokenValidator):
    """Verifies JWTs issued by the local dev/test auth provider.

    The local tokens carry the roles claim both unqualified (as the frontend
    reads it) and project-qualified (as Zitadel introspection returns it).
    """

    def _roles_claim_keys(self) -> tuple[str, ...]:
        keys = ("urn:zitadel:iam:org:project:roles",)
        project = getattr(settings, "ZITADEL_PROJECT", "")
        if project:
            keys = keys + (f"urn:zitadel:iam:org:project:{project}:roles",)
        return keys

    def __call__(
        self,
        token_string: str,
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> dict[str, Any] | None:
        from server.apps.local_auth import tokens as local_tokens

        try:
            claims = local_tokens.verify_access_token(token_string)
        except ValueError:
            return None

        # Shape the JWT claims like an introspection response so the shared
        # validate_token logic applies unchanged.
        token: dict[str, Any] = {
            "active": True,
            "exp": claims.get("exp", 0),
            "scope": " ".join(claims.get("scope", [])),
            "sub": claims.get("sub"),
        }
        for key in self._roles_claim_keys():
            if key in claims:
                token[key] = claims[key]

        try:
            self.validate_requirements(token, scopes, roles, groups, request)
        except ValidatorError:
            return None
        return token


def _select_validator() -> BaseTokenValidator | None:
    """Pick the token validator from the active auth mode (if any)."""
    if settings.OIDC_ENABLED:
        return ZitadelIntrospectTokenValidator()
    if settings.LOCAL_AUTH_ENABLED:
        return LocalJWTValidator()
    return None


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
        self.validator = _select_validator()

    def authenticate(self, request: Any, token: str) -> dict[str, Any] | None:
        if self.validator is None:
            raise HttpError(
                401,
                "Authentication is not configured on this server "
                "(OIDC and local auth are both disabled).",
            )
        return self.validator(
            token_string=token,
            scopes=self.scopes,
            roles=self.roles,
            groups=self.groups,
            request=request,
        )
