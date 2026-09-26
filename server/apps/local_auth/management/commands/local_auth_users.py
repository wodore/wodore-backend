"""Idempotent bootstrap for the built-in auth provider (spec: account-management).

Creates the dev/test fixture users with their Django groups, the SPA's
public PKCE OAuth client, and — in development/test only — a password-grant
client so scripts and tests can fetch tokens with a simple POST (parity with
the retired hand-rolled provider).
"""

from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandParser

ADMIN_USER = "admin@local.test"
EDITOR_USER = "editor@local.test"

DEV_PASSWORD_CLIENT_ID = "wodore-local-dev-password"
DEV_PASSWORD_CLIENT_SECRET = "wodore-local-dev-secret"


def _default_redirect_uris() -> list[str]:
    raw = getattr(settings, "LOCAL_AUTH_REDIRECT_URIS", "")
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return [
        "http://testserver/auth/signin-callback",
        "http://localhost:9000/auth/signin-callback",
    ]


class Command(BaseCommand):
    help = (
        "Create or refresh the built-in provider's fixture users, groups and "
        "OAuth clients. Idempotent: everything is created once; passwords "
        "are reset on every run."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--admin-password",
            default="admin-dev",
            help="Password for the admin user (default: admin-dev)",
        )
        parser.add_argument(
            "--editor-password",
            default="editor-dev",
            help="Password for the editor user (default: editor-dev)",
        )

    def handle(
        self,
        admin_password: str,
        editor_password: str,
        *args: Any,
        **options: Any,
    ) -> None:
        admin_group, _ = Group.objects.get_or_create(name="admin")
        editor_group, _ = Group.objects.get_or_create(name="editor")
        for extra in ("root", "viewer"):
            Group.objects.get_or_create(name=extra)

        created = []
        admin = self._upsert_user(
            ADMIN_USER, admin_password, [admin_group, editor_group], created
        )
        editor = self._upsert_user(
            EDITOR_USER, editor_password, [editor_group], created
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()

        self._seed_clients()

        self.stdout.write(
            self.style.SUCCESS(
                f"Built-in provider ready: {ADMIN_USER} (groups: "
                f"{', '.join(g.name for g in admin.groups.all())}), "
                f"{EDITOR_USER} (groups: "
                f"{', '.join(g.name for g in editor.groups.all())})"
                f"{' - created ' + ', '.join(created) if created else ''}"
            )
        )

    def _upsert_user(
        self,
        email: str,
        password: str,
        groups: list[Group],
        created: list[str],
    ) -> User:
        user, was_created = User.objects.get_or_create(
            username=email, defaults={"email": email}
        )
        if was_created:
            created.append(email)
        user.email = email
        user.is_active = True
        user.set_password(password)
        user.save()
        user.groups.set(groups)
        return user

    def _seed_clients(self) -> None:
        from oauth2_provider.models import get_application_model

        application_model = get_application_model()

        # SPA: public PKCE client (no secret), auth-code + RS256 JWTs,
        # consent screen skipped (first-party app).
        application_model.objects.update_or_create(
            client_id=settings.LOCAL_AUTH_CLIENT_ID,
            defaults={
                "name": "Wodore SPA (public PKCE)",
                "client_type": application_model.CLIENT_PUBLIC,
                "authorization_grant_type": (
                    application_model.GRANT_AUTHORIZATION_CODE
                ),
                "algorithm": application_model.RS256_ALGORITHM,
                "skip_authorization": True,
                "redirect_uris": "\n".join(_default_redirect_uris()),
            },
        )

        # Dev/test convenience: password grant client (parity with the
        # retired local provider). Never in production.
        is_dev_or_test = (
            settings.DEBUG or getattr(settings, "ENVIRONMENT", "") == "test"
        )
        if is_dev_or_test:
            application_model.objects.update_or_create(
                client_id=DEV_PASSWORD_CLIENT_ID,
                defaults={
                    "name": "Wodore dev/test password grant",
                    "client_type": application_model.CLIENT_CONFIDENTIAL,
                    "authorization_grant_type": (application_model.GRANT_PASSWORD),
                    "algorithm": application_model.RS256_ALGORITHM,
                    "skip_authorization": True,
                    "redirect_uris": "",
                    "client_secret": DEV_PASSWORD_CLIENT_SECRET,
                },
            )
        else:
            application_model.objects.filter(client_id=DEV_PASSWORD_CLIENT_ID).delete()
