#!/usr/bin/env python

import os
import sys


def _prefer_cwd_checkout() -> None:
    """
    Run the checkout you are standing in, not the one the shared venv's
    editable install pins (the main checkout).

    The ``app`` / ``manage`` console scripts live in the shared ``.venv``
    (symlinked into every worktree). Without this, their imports resolve
    ``server.*`` — and this very ``manage`` module — from the main
    checkout, silently ignoring worktree code. Prepending the working
    directory, the same thing ``python manage.py`` achieves via
    ``sys.path[0]``, restores the expected behaviour.

    No-op when the current directory is not a checkout root (no
    ``manage.py`` next to the caller).
    """
    cwd = os.getcwd()
    if os.path.isfile(os.path.join(cwd, "manage.py")):
        sys.path.insert(0, cwd)


def main() -> None:
    """
    Main function.

    It does several things:
    1. Prefers the checkout in the current directory (worktree-safe)
    2. Sets default settings module, if it is not set
    3. Warns if Django is not installed
    4. Executes any given command
    """
    _prefer_cwd_checkout()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

    try:
        from django.core import management
    except ImportError:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            + "available on your PYTHONPATH environment variable? Did you "
            + "forget to activate a virtual environment?",
        )

    management.execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
