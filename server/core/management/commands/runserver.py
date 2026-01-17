from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """Custom runserver command that defaults to 0.0.0.0."""

    def add_arguments(self, parser):
        super().add_arguments(parser)
        # Set default addrport to 0.0.0.0:8000
        parser._mutually_exclusive_groups.clear()
        parser.add_argument(
            "addrport",
            nargs="?",
            default="0.0.0.0:8000",
            help=(
                "Optional port number, or ipaddr:port to run the server on. "
                "Defaults to 0.0.0.0:8000 in development."
            ),
        )
