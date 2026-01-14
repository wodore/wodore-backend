from server.core.management import CRUDCommand


class Command(CRUDCommand):
    """
    DEPRECATED: HutType is no longer a model.

    Hut types are now managed as Category objects through the Category model.
    Use the Django admin interface or Category API/management commands instead.
    This command is kept for backward compatibility but does nothing.
    """

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "The 'hut_types' command is deprecated. "
                "Hut types are now managed as Category objects. "
                "Please use the Django admin interface or Category-related commands."
            )
        )
        return
