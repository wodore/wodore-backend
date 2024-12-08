"""
This file contains all the settings that defines the development server.

SECURITY WARNING: don't run with debug turned on in production!
"""

import logging
import socket
from typing import Tuple

from server.settings.components import config
from server.settings.components.common import (
    DATABASES,
    DJANGO_TRUSTED_DOMAINS,
    INSTALLED_APPS,
    MIDDLEWARE,
)
from server.settings.components.csp import (
    CSP_CONNECT_SRC,
    CSP_SCRIPT_SRC,
)

CSP_IMG_SRC: Tuple[str, ...] = ("'self'", "data:", "https:", "http:")

# Setting the development status:


SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False
SECURE_PROXY_SSL_HEADER = None

try:
    import debug_toolbar

    DEBUG = True
except ModuleNotFoundError:
    DEBUG = False

ALLOWED_HOSTS = [
    *DJANGO_TRUSTED_DOMAINS,
    "api.localhost",
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "[::1]",
]


CSRF_TRUSTED_ORIGINS = [
    *[f"http://{d}" for d in DJANGO_TRUSTED_DOMAINS],
    *[f"https://{d}" for d in DJANGO_TRUSTED_DOMAINS],
]
# CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https?://localhost:\d+$",
    r"^localhost:\d+$",
    r"^.*\.localhost:\d+$",
    # r"^https?://wodore.com",
    # r"^https?://beta.wodore.com",
    *[f"^https?://{d}" for d in DJANGO_TRUSTED_DOMAINS],
]

# Installed apps for development only:

if DEBUG:
    INSTALLED_APPS += (
        # Better debug:
        "debug_toolbar",
        "nplusone.ext.django",
        # Linting migrations:
        "django_migration_linter",
        # django-test-migrations:
        "django_test_migrations.contrib.django_checks.AutoNames",
        # This check might be useful in production as well,
        # so it might be a good idea to move `django-test-migrations`
        # to prod dependencies and use this check in the main `settings.py`.
        # This will check that your database is configured properly,
        # when you run `python manage.py check` before deploy.
        "django_test_migrations.contrib.django_checks.DatabaseConfiguration",
        # django-extra-checks:
        "extra_checks",
    )


# Django debug toolbar:
# https://django-debug-toolbar.readthedocs.io

if DEBUG:
    MIDDLEWARE += (
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        # https://github.com/bradmontgomery/django-querycount
        # Prints how many queries were executed, useful for the APIs.
        "querycount.middleware.QueryCountMiddleware",
    )

# https://django-debug-toolbar.readthedocs.io/en/stable/installation.html#configure-internal-ips
try:  # This might fail on some OS
    INTERNAL_IPS = ["{0}.1".format(ip[: ip.rfind(".")]) for ip in socket.gethostbyname_ex(socket.gethostname())[2]]
except OSError:  # pragma: no cover
    INTERNAL_IPS = []
INTERNAL_IPS += ["127.0.0.1", "0.0.0.0"]


def _custom_show_toolbar(request) -> bool:
    """Only show the debug toolbar to users with the superuser flag."""
    return DEBUG and request.user.is_superuser


DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": "server.settings.environments.development._custom_show_toolbar",
}

# This will make debug toolbar to work with django-csp,
# since `ddt` loads some scripts from `ajax.googleapis.com`:
CSP_SCRIPT_SRC += ("ajax.googleapis.com",)
CSP_IMG_SRC += ("data:",)
CSP_CONNECT_SRC += ("'self'",)


# nplusone
# https://github.com/jmcarp/nplusone

# Should be the first in line:
if DEBUG:
    MIDDLEWARE = ("nplusone.ext.django.NPlusOneMiddleware",) + MIDDLEWARE

# Logging N+1 requests:
# NPLUSONE_RAISE = True  # comment out if you want to allow N+1 requests
NPLUSONE_LOGGER = logging.getLogger("django")
NPLUSONE_LOG_LEVEL = logging.WARN
NPLUSONE_WHITELIST = [
    {"model": "admin.*"},
]


# django-test-migrations
# https://github.com/wemake-services/django-test-migrations

# Set of badly named migrations to ignore:
DTM_IGNORED_MIGRATIONS = frozenset((("axes", "*"), ("computedfields", "0003_auto_20200713_2212")))


# django-extra-checks
# https://github.com/kalekseev/django-extra-checks

EXTRA_CHECKS = {
    "checks": [
        # Forbid `unique_together`:
        "no-unique-together",
        # Use the indexes option instead:
        # "no-index-together",
        # Each model must be registered in admin:
        "model-admin",
        # FileField/ImageField must have non empty `upload_to` argument:
        "field-file-upload-to",
        # Text fields shouldn't use `null=True`:
        # "field-text-null",
        # Don't pass `null=False` to model fields (this is django default)
        "field-null",
        # ForeignKey fields must specify db_index explicitly if used in
        # other indexes:
        {"id": "field-foreign-key-db-index", "when": "indexes"},
        # If field nullable `(null=True)`,
        # then default=None argument is redundant and should be removed:
        "field-default-null",
        # Fields with choices must have companion CheckConstraint
        # to enforce choices on database level
        "field-choices-constraint",
    ],
}

# Disable persistent DB connections
# https://docs.djangoproject.com/en/4.2/ref/databases/#caveats
DATABASES["default"]["CONN_MAX_AGE"] = 0
