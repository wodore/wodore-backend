"""Staticfiles parity for the demos app.

The docker image runs ``DJANGO_ENV=test collectstatic``
(docker/django/Dockerfile.*), so an app missing from the test
environment's INSTALLED_APPS silently loses its static files in every
built image — on dev machines and in CI the app happens to be
registered via development.py's ``WITH_DEV`` extras, which masked the
bug until /static/demos/vendor/* 404ed on staging.

These tests pin the test-env registration by asserting the staticfiles
finders can locate every file the app ships.
"""

from pathlib import Path

from django.contrib.staticfiles import finders

import server.apps.demos

APP_STATIC_DIR = Path(server.apps.demos.__file__).parent / "static"


def test_demos_app_installed() -> None:
    """The app is registered in the test environment (collectstatic parity)."""
    from django.apps import apps

    assert apps.is_installed("server.apps.demos")


def test_all_demos_static_files_discoverable() -> None:
    """Every shipped static file is found by the configured finders.

    If this fails after adding the app to a new environment, mirror the
    INSTALLED_APPS registration from staging.py there (see
    server/settings/environments/test.py).
    """
    shipped = sorted(
        path.relative_to(APP_STATIC_DIR).as_posix()
        for path in APP_STATIC_DIR.rglob("*")
        if path.is_file()
    )
    assert shipped, "demos app unexpectedly ships no static files"

    missing = [name for name in shipped if finders.find(name) is None]
    assert not missing, f"static files not discoverable by collectstatic: {missing}"
