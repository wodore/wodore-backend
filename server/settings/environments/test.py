"""Test environment settings."""

from server.settings.environments.development import *

ENVIRONMENT = "test"
DEBUG = False

# The dev environment star-import above can drag the debug toolbar
# middleware along (present on dev machines, absent in CI). It renders
# toolbars into HTML responses based on REMOTE_ADDR alone - strip it so
# test responses are clean everywhere.
MIDDLEWARE = tuple(m for m in MIDDLEWARE if "debug_toolbar" not in m)

# Use faster password hasher in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable email sending in tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Dev demo pages (mapcompare etc.): registered here as well, NOT for the
# URLs (DEMOS_ENABLED stays unset) but for `collectstatic`: the docker
# image collects under DJANGO_ENV=test (docker/django/Dockerfile.*), and
# an app missing from INSTALLED_APPS never reaches STATIC_ROOT. That
# shipped a staging build where /demos/mapcompare/ rendered but every
# /static/demos/vendor/* asset 404ed — development.py only registers the
# app when dev extras (debug_toolbar) are installed, which is true on
# dev machines and in CI, false in the production-deps image.
# Membership check: environments/test.py star-imports development, so
# with dev extras installed the app is already present.
if "server.apps.demos" not in INSTALLED_APPS:
    INSTALLED_APPS += ("server.apps.demos",)  # pyright: ignore[reportUndefinedVariable]
