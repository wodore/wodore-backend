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
