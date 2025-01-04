from mozilla_django_oidc.auth import OIDCAuthenticationBackend

# from django.contrib import admin
# from django.contrib.auth.models import Permission, User
from django.contrib.auth.models import Group, User


class PermissionBackend(OIDCAuthenticationBackend):  # type: ignore[no-any-unimported]
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
