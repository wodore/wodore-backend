from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """Custom runserver command that defaults to 0.0.0.0:8000.

    The default is applied in ``handle`` instead of by re-registering the
    ``addrport`` argument: re-adding the positional (after clearing the
    mutually exclusive group) created a *second* argparse positional with the
    same dest, whose default silently overrode any explicitly given
    addr/port - ``runserver 127.0.0.1:8010`` always bound 0.0.0.0:8000.
    """

    def handle(self, addrport: str | None = None, **options) -> None:
        if not addrport:
            addrport = "0.0.0.0:8000"
        super().handle(addrport=addrport, **options)
