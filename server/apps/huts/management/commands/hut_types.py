from typing import Any, override

from django_admin_runner import register_command

from server.apps.huts.models import Hut
from server.core.management import CRUDCommand


@register_command(group="Huts")
class Command(CRUDCommand[Hut]):
    help = "Deprecated: hut types are Category objects now; this command does nothing."

    """
    DEPRECATED: HutType is no longer a model.

    Hut types are now managed as Category objects through the Category model.
    Use the Django admin interface or Category API/management commands instead.
    This command is kept for backward compatibility but does nothing.
    """

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(
            self.style.WARNING(
                "The 'hut_types' command is deprecated. "
                "Hut types are now managed as Category objects. "
                "Please use the Django admin interface or Category-related commands."
            )
        )
