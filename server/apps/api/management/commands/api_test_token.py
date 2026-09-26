"""Mint a built-in-provider access token for API testing (spec: optional-oidc).

Prints an RS256 JWT signed with the provider key, carrying the same claims
DOT issues (roles from Django groups) - usable directly against
``AuthBearer``-protected endpoints. Requires ``OIDC_ENABLED`` (default on).
"""

from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Mint a built-in provider access token for a user (API testing)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "-u",
            "--user",
            help="User email (fixture users: admin@local.test, editor@local.test)",
            default="admin@local.test",
        )
        parser.add_argument(
            "--issuer",
            default="http://localhost:8000/oauth/local",
            help="Issuer to embed in the token (default: http://localhost:8000/oauth/local)",
        )
        parser.add_argument(
            "-l", "--list-users", help="List available user emails", action="store_true"
        )

    def handle(
        self,
        user: str,
        issuer: str,
        list_users: bool,
        *args: Any,
        **options: Any,
    ) -> None:
        from server.apps.local_auth import tokens

        if not settings.OIDC_ENABLED:
            raise CommandError(
                "OIDC is disabled (OIDC_ENABLED=false) - the built-in "
                "provider is not available."
            )
        if list_users:
            for u in User.objects.filter(is_active=True).values_list(
                "email", flat=True
            ):
                if u:
                    print(u)
            return
        try:
            user_obj = User.objects.get(username=user, is_active=True)
        except User.DoesNotExist:
            try:
                user_obj = User.objects.get(email=user, is_active=True)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"user '{user}' not found (see --list-users)")
                )
                raise CommandError(1)
        token = tokens.issue_access_token(
            user_obj, issuer, settings.LOCAL_AUTH_CLIENT_ID
        )
        print(token)
