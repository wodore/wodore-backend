from urllib.parse import urlparse

import requests
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

# from django.contrib import admin
# from django.contrib.auth.models import Permission, User
from django.contrib.auth.models import Group, User


class PermissionBackend(OIDCAuthenticationBackend):  # type: ignore[no-any-unimported]
    def _prepare_request_with_custom_host(self, url: str, request_kwargs: dict = None):
        """
        Modify URL and headers if OIDC_ISSUER_INTERNAL_URL is configured.
        This allows using an internal service URL while preserving the public hostname in the Host header.

        Use case: When OIDC provider requires a specific Host header (e.g., in local/dev Kubernetes clusters
        where DNS resolution needs to be overridden).
        """
        if request_kwargs is None:
            request_kwargs = {}

        internal_url = self.get_settings("OIDC_ISSUER_INTERNAL_URL", "")

        if internal_url:
            parsed_original = urlparse(url)
            parsed_internal = urlparse(internal_url)

            # Replace scheme and netloc with internal URL, keep path
            modified_url = url.replace(
                f"{parsed_original.scheme}://{parsed_original.netloc}",
                f"{parsed_internal.scheme}://{parsed_internal.netloc}",
            )

            # Add Host header with original hostname
            headers = request_kwargs.setdefault("headers", {})
            headers["Host"] = parsed_original.netloc

            return modified_url, request_kwargs

        return url, request_kwargs

    def retrieve_matching_jwk(self, token):
        """Override to add Host header support for JWKS endpoint"""
        import json
        from base64 import urlsafe_b64decode

        url, kwargs = self._prepare_request_with_custom_host(self.OIDC_OP_JWKS_ENDPOINT)
        response_jwks = requests.get(
            url,
            verify=self.get_settings("OIDC_VERIFY_SSL", True),
            timeout=self.get_settings("OIDC_TIMEOUT", None),
            proxies=self.get_settings("OIDC_PROXY", None),
            **kwargs,
        )
        response_jwks.raise_for_status()
        jwks = response_jwks.json()

        # Decode the JWT header to get the key ID
        # JWT format: header.payload.signature (each base64url encoded)
        header_segment = token.split(b".")[0]
        # Add padding if needed for base64 decoding
        padding = b"=" * (4 - (len(header_segment) % 4))
        header_data = urlsafe_b64decode(header_segment + padding)
        header = json.loads(header_data)

        # Find and return the matching key dict from the JWKS
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == header.get("kid"):
                return jwk

        return None

    def get_token(self, payload):
        """Override to add Host header support for token endpoint"""
        auth = None
        if self.get_settings("OIDC_TOKEN_USE_BASIC_AUTH", False):
            auth = (self.OIDC_RP_CLIENT_ID, self.OIDC_RP_CLIENT_SECRET)

        url, kwargs = self._prepare_request_with_custom_host(
            self.OIDC_OP_TOKEN_ENDPOINT
        )

        response = requests.post(
            url,
            data=payload,
            auth=auth,
            verify=self.get_settings("OIDC_VERIFY_SSL", True),
            timeout=self.get_settings("OIDC_TIMEOUT", None),
            proxies=self.get_settings("OIDC_PROXY", None),
            **kwargs,
        )

        response.raise_for_status()
        return response.json()

    def get_userinfo(self, access_token, id_token, payload):
        """Override to add Host header support for userinfo endpoint"""
        url, kwargs = self._prepare_request_with_custom_host(self.OIDC_OP_USER_ENDPOINT)

        user_response = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            verify=self.get_settings("OIDC_VERIFY_SSL", True),
            timeout=self.get_settings("OIDC_TIMEOUT", None),
            proxies=self.get_settings("OIDC_PROXY", None),
            **kwargs,
        )

        user_response.raise_for_status()
        return user_response.json()

    def get_username(self, claims: dict) -> str | None:
        return claims.get("sub")

    def get_groups(self, claims: dict) -> list[str]:
        permClaim = (
            "urn:zitadel:iam:org:project:"
            + self.get_settings("ZITADEL_PROJECT")
            + ":roles"
        )
        if permClaim in claims:
            return [k.replace("group:", "") for k in claims[permClaim] if "group:" in k]
        return ["user"]

    def get_permissions(self, claims: dict) -> list[str]:
        permClaim = (
            "urn:zitadel:iam:org:project:"
            + self.get_settings("ZITADEL_PROJECT")
            + ":roles"
        )
        if permClaim in claims:
            # return [k.replace("perm:", "") for k in claims[permClaim] if "perm:" in k]
            return [k for k in claims[permClaim] if "perm:" in k]
        return []

    def update_user_groups(self, user: User, claims: dict) -> User:
        zitadel_groups = self.get_groups(claims)
        zitadel_perms = self.get_permissions(claims)
        user_groups = list(user.groups.all())
        zitadel_groups_perms = zitadel_groups + zitadel_perms
        for zgroup in zitadel_groups_perms:
            if zgroup not in [u.name for u in user_groups]:
                try:
                    new_group = Group.objects.get(name=zgroup)
                except Group.DoesNotExist:
                    new_group = Group(name=zgroup)
                    new_group.save()
                user.groups.add(new_group)
        for ugroup in user_groups:
            if ugroup.name not in zitadel_groups_perms:
                user.groups.remove(ugroup)
        return user

    def create_user(self, claims: dict) -> User:
        username = self.get_username(claims)
        user = self.UserModel.objects.create_user(username)  # , email=email)
        return self.update_user(user, claims)
        # return self.UserModel.objects.none()

    def update_user(self, user: User, claims: dict) -> User:
        user.email = claims.get("email")
        user.first_name = claims.get("given_name")
        user.last_name = claims.get("family_name")
        zitadel_groups = self.get_groups(claims)
        # default:
        user.is_superuser = False
        user.is_staff = False
        if "admin" in zitadel_groups or "root" in zitadel_groups:
            user.is_superuser = True
            user.is_staff = True
        elif "editor" in zitadel_groups or "viewer" in zitadel_groups:
            user.is_superuser = False
            user.is_staff = True
        self.update_user_groups(user, claims)
        user.save()
        return user
