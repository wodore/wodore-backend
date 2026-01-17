"""
This file contains all the settings that defines the development server.

SECURITY WARNING: don't run with debug turned on in production!
"""

import logging
import re
import socket
import subprocess
from importlib.util import find_spec

from server.settings.components.common import (
    DATABASES,
    DJANGO_TRUSTED_DOMAINS,
    INSTALLED_APPS,
    MIDDLEWARE,
)
from server.settings.components.csp import CONTENT_SECURITY_POLICY
from server.settings.components.oicd import discovery_info

# Setting the development status:

ENVIRONMENT = "development"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False
SECURE_PROXY_SSL_HEADER = None

DEBUG = True
# try:
#    import debug_toolbar
#
#    WITH_DEV = True
# except ModuleNotFoundError:
#    WITH_DEV = False

WITH_DEV = find_spec("debug_toolbar") is not None


# Get local IP address dynamically
def get_local_ip() -> str | None:
    """Get the local IP address using the route to 8.8.8.8."""
    try:
        result = subprocess.run(
            ["ip", "-o", "route", "get", "to", "8.8.8.8"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Extract IP from output: "192.168.1.50 dev eth0 src 192.168.1.50 uid 0"
        # Using the sed command approach
        import re

        match = re.search(r"src (\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


LOCAL_IP = get_local_ip()

ALLOWED_HOSTS = [
    *DJANGO_TRUSTED_DOMAINS,
    "api.localhost",
    "hub.localhost",
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "[::1]",
]

# Add local IP dynamically if available
if LOCAL_IP:
    ALLOWED_HOSTS.append(LOCAL_IP)


CSRF_TRUSTED_ORIGINS = [
    *[f"http://{d}" for d in DJANGO_TRUSTED_DOMAINS],
    *[f"https://{d}" for d in DJANGO_TRUSTED_DOMAINS],
]
# CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https?://localhost:\d+$",
    r"^localhost:\d+$",
    r"^.*\.localhost:\d+$",
    *[f"^https?://{d}" for d in DJANGO_TRUSTED_DOMAINS],
]

# Add local IP pattern to CORS dynamically
if LOCAL_IP:
    # Match the specific local IP on any port
    CORS_ALLOWED_ORIGIN_REGEXES.append(rf"^https?://{re.escape(LOCAL_IP)}:\d+$")
    # Also match the entire subnet (e.g., 192.168.1.x)
    ip_parts = LOCAL_IP.split(".")
    if len(ip_parts) == 4:
        subnet_pattern = r"^https?://" + r"\.".join(ip_parts[:3]) + r"\.\d+:\d+$"
        CORS_ALLOWED_ORIGIN_REGEXES.append(subnet_pattern)

# Installed apps for development only:

if WITH_DEV:
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

if WITH_DEV:
    MIDDLEWARE += (
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        # https://github.com/bradmontgomery/django-querycount
        # Prints how many queries were executed, useful for the APIs.
        "querycount.middleware.QueryCountMiddleware",
    )

if discovery_info:  # use only if setup correct
    MIDDLEWARE += ("mozilla_django_oidc.middleware.SessionRefresh",)

# https://django-debug-toolbar.readthedocs.io/en/stable/installation.html#configure-internal-ips
try:  # This might fail on some OS
    INTERNAL_IPS = [
        "{0}.1".format(ip[: ip.rfind(".")])
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]
    ]
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
CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"] += ("ajax.googleapis.com",)
CONTENT_SECURITY_POLICY["DIRECTIVES"]["connect-src"] += ("'self'",)
CONTENT_SECURITY_POLICY["DIRECTIVES"]["img-src"] += ("http:",)


# nplusone
# https://github.com/jmcarp/nplusone

# Should be the first in line:
if WITH_DEV:
    MIDDLEWARE = ("nplusone.ext.django.NPlusOneMiddleware", *MIDDLEWARE)

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
DTM_IGNORED_MIGRATIONS = frozenset(
    (("axes", "*"), ("computedfields", "0003_auto_20200713_2212"))
)


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
