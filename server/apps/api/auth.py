import json
import time
from typing import Any, Dict

import requests
from authlib.integrations.django_oauth2 import ResourceProtector
from authlib.jose import jwt
from authlib.oauth2.rfc7662 import IntrospectTokenValidator
from ninja.security import HttpBearer

from django.conf import settings

# API_PRIVATE_KEY_FILE: dict[str, str] = {}


class ValidatorError(Exception):
    def __init__(self, error: Dict[str, str], status_code: int):
        super().__init__()
        self.error = error
        self.status_code = status_code


class ZitadelIntrospectTokenValidator(IntrospectTokenValidator):  # type: ignore[no-any-unimported]
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.__api_private_key = (
            settings.ZITADEL_API_PRIVATE_KEY
            if settings.ZITADEL_API_PRIVATE_KEY
            else self._load_api_private_key_from_file(settings.ZITADEL_API_PRIVATE_KEY_FILE_PATH)
        )

    def _load_api_private_key_from_file(self, file_path: str) -> dict[str, str]:
        _key_obj = {}
        with open(file_path) as f:
            data = json.load(f)
            _key_obj["client_id"] = data["clientId"]
            _key_obj["key_id"] = data["keyId"]
            _key_obj["private_key"] = data["key"]
        return _key_obj

    def introspect_token(self, token_string: str) -> dict[str, Any]:
        # Create JWT for client assertion
        payload = {
            "iss": self.__api_private_key["client_id"],
            "sub": self.__api_private_key["client_id"],
            "aud": settings.OIDC_OP_BASE_URL,
            "exp": int(time.time()) + 60 * 60,  # Expires in 1 hour
            "iat": int(time.time()),
        }
        header = {"alg": settings.OIDC_RP_SIGN_ALGO, "kid": self.__api_private_key["key_id"]}
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
        response = requests.post(settings.OIDC_OP_INTROSPECTION_ENDPOINT, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()
        return token_data

    def match_token_scopes(self, token: dict[str, str], or_scopes: list[str] | None) -> bool:
        if or_scopes is None:
            return True
        scopes = token.get("scope", "").split()
        for and_scopes in or_scopes:
            if all(key in scopes for key in and_scopes.split()):
                return True
        return False

    def match_token_and_roles(self, token: dict[str, str], and_roles: list[str] | None) -> bool:
        if and_roles is None:
            return True
        roles = [
            g
            for g in token.get(f"urn:zitadel:iam:org:project:{settings.ZITADEL_PROJECT}:roles", "")
            if "group:" not in g
        ]
        return all(role in roles for role in and_roles)

    def match_token_groups(self, token: dict[str, str], or_groups: list[str] | None) -> bool:
        if or_groups is None:
            return True
        groups = [
            g.replace("group:", "")
            for g in token.get(f"urn:zitadel:iam:org:project:{settings.ZITADEL_PROJECT}:roles", "")
            if "group:" in g
        ]
        return any(group in groups for group in or_groups)

    def validate_token(
        self,
        token: dict[str, Any],
        scopes: list[str] | None,
        roles: list[str] | None,
        groups: list[str] | None,
        request: Any,
    ) -> None:
        now = int(time.time())
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
        if not self.match_token_and_roles(token, roles) and not self.match_token_groups(token, groups):
            raise ValidatorError(
                {
                    "code": "insufficient_permission",
                    "description": f"Token has insufficient permission. Roles required: {roles} or group required: {groups}",
                },
                401,
            )
        # if not self.match_token_groups(token, groups):
        #    raise ValidatorError(
        #        {
        #            "code": "insufficient_group",
        #            "description": f"Token has insufficient group. Group requires: {groups}",
        #        },
        #        401,
        #    )

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
            self.validate_token(token, scopes, roles, groups, request)
        except ValidatorError as e:
            # print(f"Unauthorized: {e.error}")
            return None
        # TODO: return user with permission and groups
        return token


require_auth = ResourceProtector()
require_auth.register_token_validator(ZitadelIntrospectTokenValidator())


class AuthBearer(HttpBearer):
    validator = ZitadelIntrospectTokenValidator()

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

    def authenticate(self, request: Any, token: str) -> dict[str, Any] | None:
        return self.validator(
            token_string=token, scopes=self.scopes, roles=self.roles, groups=self.groups, request=request
        )
