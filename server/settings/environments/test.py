"""Test environment settings."""

from server.settings.environments.development import *  # noqa: F401, F403, WPS433

ENVIRONMENT = "test"
DEBUG = False

# Use faster password hasher in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable email sending in tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
