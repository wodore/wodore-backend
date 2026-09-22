"""Create/refresh the local dev/test users for the built-in auth provider."""

from typing import Any

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandParser

ADMIN_USER = "admin@local.test"
EDITOR_USER = "editor@local.test"


class Command(BaseCommand):
    help = (
        "Create or refresh the local dev/test users used by the built-in auth "
        "provider (LOCAL_AUTH_ENABLED). Idempotent: users and groups are "
        "created once; passwords are reset on every run."
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

        created = []
        admin = self._upsert_user(
            ADMIN_USER, admin_password, [admin_group, editor_group], created
        )
        editor = self._upsert_user(
            EDITOR_USER, editor_password, [editor_group], created
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Local auth users ready: {ADMIN_USER} (groups: "
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
