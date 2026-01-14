"""
Django settings for server project.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their config, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

import os
import subprocess

# Set the environment variables - fix boto3 issue when uploading file
# https://stackoverflow.com/questions/79375793/s3uploadfailederror-due-to-missingcontentlength-when-calling-putobject-in-mlflow
os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
os.environ["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"

from typing import Dict, List, Tuple, Union

from corsheaders.defaults import default_headers
from hut_services import SERVICES

from django.utils.translation import gettext_lazy as _

from server.settings.components import BASE_DIR, config

try:
    from hut_services_private import SERVICES as PRIVATE_SERVICES
except ImportError:
    PRIVATE_SERVICES = {}

if PRIVATE_SERVICES:
    SERVICES.update(PRIVATE_SERVICES)  # type: ignore pyright

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

SECRET_KEY = config("DJANGO_SECRET_KEY", "NotSet")


# Git version/hash for cache busting and version tracking
def _get_git_hash() -> str:
    """Get git hash from env var or git command (dev mode only)."""
    # First try environment variable (for production/docker)
    git_hash = config("GIT_HASH", default=None)
    if git_hash:
        return git_hash

    # In development, try to get from git if available
    # This requires DEBUG to be set, but we check if we're likely in dev mode
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # Git not available or not a git repo
        return "unknown"


GIT_HASH = _get_git_hash()


# Build timestamp for version tracking
def _get_build_timestamp() -> str:
    """Get build timestamp from env var or current time."""
    from datetime import datetime

    # First try environment variable (for production/docker)
    build_timestamp = config("BUILD_TIMESTAMP", default=None)
    if build_timestamp:
        return build_timestamp

    # In development, use current timestamp
    return datetime.now().isoformat()


BUILD_TIMESTAMP = _get_build_timestamp()

DJANGO_TRUSTED_DOMAINS = (
    [d.strip() for d in config("DJANGO_TRUSTED_DOMAINS").split(",")]
    if config("DJANGO_TRUSTED_DOMAINS", "")
    else []
)
FRONTEND_DOMAIN = (
    config("FRONTEND_DOMAIN")
    if config("FRONTEND_DOMAIN", None)
    else "http://localhost:9000"
)

DJANGO_ADMIN_URL = (
    config("DJANGO_ADMIN_URL")
    if config("DJANGO_ADMIN_URL", None)
    else "http://localhost:8000"
)

# Application definition:

INSTALLED_APPS: Tuple[str, ...] = (
    # my server core:
    "server.core.apps.CoreConfig",
    # my apps:
    "server.apps.manager",
    "server.apps.main",
    "server.apps.meta_image_field",
    "server.apps.images",
    "server.apps.symbols",
    "server.apps.organizations",
    "server.apps.licenses",
    "server.apps.contacts",
    "server.apps.feedbacks",
    "server.apps.owners",
    "server.apps.categories",
    "server.apps.huts",
    "server.apps.availability",
    "server.apps.external_geonames",
    "server.apps.geometries",
    "server.apps.api",
    # Extension:
    "pgtrigger",  # https://django-pgtrigger.readthedocs.io/
    "ninja",
    "colorfield",
    "jsoneditor",
    "modeltrans",
    "django_jsonform",
    "jsonsuit.apps.JSONSuitConfig",  # https://github.com/tooreht/django-jsonsuit
    "django_countries",
    "computedfields",  # https://github.com/netzkolchose/django-computedfields
    "django_extensions",  # https://django-extensions.readthedocs.io/
    "corsheaders",  # https://github.com/adamchainz/django-cors-headers
    # "leaflet",  # https://django-leaflet.readthedocs.io/en/latest/index.html
    # Default django apps:
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",  # serve also in dev mode with whitenoise
    "django.contrib.staticfiles",
    # cloudinary_storage needs to be before django.contrib.staticfiles if used for static files as well!
    # "cloudinary_storage",  # https://pypi.org/project/django-cloudinary-storage/
    # "cloudinary",
    "django.contrib.gis",
    # django-admin:
    # "admin_volt.apps.AdminVoltConfig",  # https://github.com/app-generator/django-admin-volt
    # "grappelli",  # https://django-grappelli.readthedocs.io/en/latest/
    # "admin_interface",  # https://github.com/fabiocaccamo/django-admin-interface
    "unfold",  # https://github.com/unfoldadmin/django-unfold
    "unfold.contrib.filters",  # optional, if special filters are needed
    "unfold.contrib.forms",  # optional, if special form elements are needed
    "unfold.contrib.inlines",  # optional, if special inlines are needed
    # "unfold.contrib.import_export",  # optional, if django-import-export package is used
    # "unfold.contrib.guardian",  # optional, if django-guardian package is used
    # "unfold.contrib.simple_history",  # optional, if django-simple-history package is used
    "django.contrib.admin",
    "django.contrib.admindocs",
    # Security:
    "axes",
    "mozilla_django_oidc",  # Load after auth https://github.com/mozilla/mozilla-django-oidc
    "csp",
    # Health checks:
    # You may want to enable other checks as well,
    # see: https://github.com/KristianOellegaard/django-health-check
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
    "django_cleanup.apps.CleanupConfig",  # https://pypi.org/project/django-cleanup/
)

MIDDLEWARE: Tuple[str, ...] = (
    # Environment identification header:
    "server.middleware.headers.EnvironmentHeadersMiddleware",
    # Logging:
    "server.settings.components.logging.LoggingContextVarsMiddleware",
    # Cross-Origin Resource Sharing (CORS)
    "corsheaders.middleware.CorsMiddleware",
    # Content Security Policy:
    "csp.middleware.CSPMiddleware",
    # Django:
    "django.middleware.security.SecurityMiddleware",
    # Whitenoise
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # django-permissions-policy
    "django_permissions_policy.PermissionsPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Login
    # "mozilla_django_oidc.middleware.SessionRefresh", # added in the environment files
    # Axes:
    "axes.middleware.AxesMiddleware",
    # Django HTTP Referrer Policy:
    "django_http_referrer_policy.middleware.ReferrerPolicyMiddleware",
)


CORS_ALLOW_HEADERS = [*default_headers, "access-control-allow-origin"]

ROOT_URLCONF = "server.urls"

WSGI_APPLICATION = "server.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": config("POSTGRES_DB", ""),
        "USER": config("POSTGRES_USER", ""),
        "PASSWORD": config("POSTGRES_PASSWORD", ""),
        "HOST": config("DJANGO_DATABASE_HOST", ""),
        "PORT": config("DJANGO_DATABASE_PORT", cast=int, default=0),
        "CONN_MAX_AGE": config("CONN_MAX_AGE", cast=int, default=60),
        "OPTIONS": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=15000ms",
        },
    },
}

DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
if config("AWS_ACCESS_KEY_ID", ""):
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    # AWS_S3_CUSTOM_DOMAIN = config("AWS_S3_CUSTOM_DOMAIN")
    AWS_S3_ENDPOINT_URL = (
        config("AWS_S3_ENDPOINT_URL")
        if config("AWS_S3_ENDPOINT_URL", "")
        else f"https://{config('AWS_S3_CUSTOM_DOMAIN')}"
    )
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ADDRESSING_STYLE = "path"
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME")
    AWS_S3_SECURE_URLS = True
    AWS_S3_USE_SSL = True
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False  # Overwrite files with same name
    AWS_DEFAULT_ACL = "public-read"  # Recommended with rclone proxy
    AWS_QUERYSTRING_EXPIRE = 3600 * 24 * 7  # max 7 days
    AWS_S3_SIGNATURE_VERSION = "s3v4"


STORAGES = {
    "default": {
        "BACKEND": DEFAULT_FILE_STORAGE,
    },
    "staticfiles": {
        # "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

# LANGUAGE_CODE = 'en-us'
LANGUAGE_CODE = "de"
# LANGUAGE_CODE = 'fr'

# USE_I18N = True
USE_I18N = True

LANGUAGES = (
    ("de", _("German")),
    ("en", _("English")),
    ("fr", _("French")),
    ("it", _("Italian")),
)

LANGUAGE_CODES = [lang[0] for lang in LANGUAGES]
LOCALE_PATHS = ("locale/",)

USE_TZ = True
# TIME_ZONE = 'UTC'
TIME_ZONE = "Europe/Zurich"

MODELTRANS_FALLBACK = {
    "default": (LANGUAGE_CODE,),
    "de": ("en", "fr"),
    "en": ("de", "fr"),
    "it": ("fr", "de", "en"),
    "fr": ("it", "de", "en"),
}
COUNTRIES_ONLY = ["DE", "CH", "AT", "FR", "IT"]


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR.joinpath("static")

STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
)

# https://github.com/cshum/imagor
IMAGOR_URL = config("IMAGOR_URL", "")
IMAGOR_KEY = config("IMAGOR_KEY", None)
# Templates
# https://docs.djangoproject.com/en/4.2/ref/templates/api

TEMPLATES = [
    {
        "APP_DIRS": True,
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            # Contains plain text templates, like `robots.txt`:
            BASE_DIR.joinpath("server", "templates"),
        ],
        "OPTIONS": {
            "context_processors": [
                # Default template context processors:
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.request",
                # grappelli
                # "django.template.context_processors.request",
            ],
        },
    }
]


# Media files
# Media root dir is commonly changed in production
# (see development.py and production.py).
# https://docs.djangoproject.com/en/4.2/topics/files/

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR.joinpath("media")


# Django authentication system
# https://docs.djangoproject.com/en/4.2/topics/auth/

AUTHENTICATION_BACKENDS = (
    "axes.backends.AxesBackend",
    "django.contrib.auth.backends.ModelBackend",
    "server.core.oicd_permission.PermissionBackend",
)

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]


# Security
# https://docs.djangoproject.com/en/4.2/topics/security/

# is overwritten for dev in enviroment
SESSION_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Session settings
# https://docs.djangoproject.com/en/4.2/ref/settings/#sessions
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 7 days (in seconds)
SESSION_SAVE_EVERY_REQUEST = True  # Extend session on every request
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie


CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# X_FRAME_OPTIONS = "DENY"
X_FRAME_OPTIONS = "SAMEORIGIN"  # django-admin-interface
SILENCED_SYSTEM_CHECKS = ["security.W019"]  # django-admin-interface

# https://github.com/DmytroLitvinov/django-http-referrer-policy
# https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy
REFERRER_POLICY = "same-origin"

# https://github.com/adamchainz/django-permissions-policy#setting
PERMISSIONS_POLICY: Dict[str, Union[str, List[str]]] = {}


# Timeouts
# https://docs.djangoproject.com/en/4.2/ref/settings/#std:setting-EMAIL_TIMEOUT

EMAIL_TIMEOUT = 5


# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"


JSONSUIT_WIDGET_THEME = "tomorrow"

# Translations

DEEPL_KEY = config("DEEPL_KEY", None)


# Availability Tracking Settings
# Configuration for hut availability update priorities and intervals

AVAILABILITY_UPDATE_SETTINGS = {
    # Time intervals (in minutes) for different priority levels
    "HIGH_PRIORITY_MINUTES": config(
        "AVAILABILITY_HIGH_PRIORITY_MINUTES", cast=int, default=30
    ),
    "MEDIUM_PRIORITY_MINUTES": config(
        "AVAILABILITY_MEDIUM_PRIORITY_MINUTES", cast=int, default=180
    ),  # 3 hours
    "LOW_PRIORITY_MINUTES": config(
        "AVAILABILITY_LOW_PRIORITY_MINUTES", cast=int, default=1440
    ),  # 24 hours
    "INACTIVE_PRIORITY_MINUTES": config(
        "AVAILABILITY_INACTIVE_PRIORITY_MINUTES", cast=int, default=10080
    ),  # 7 days
    # Date range for priority-based selection (days)
    "NEXT_DAYS": config("AVAILABILITY_NEXT_DAYS", cast=int, default=14),
}


# Hut Categories Settings
# Configuration for hut type categories

# Category parent for hut types
# Format: "parent.child" or "root_slug"
# This defines where hut categories (hut, bivouac, etc.) are located in the category hierarchy
# Note: The migration creates "accommodation" at root level, not "map.accommodation"
HUTS_CATEGORY_PARENT = config("HUTS_CATEGORY_PARENT", default="accommodation")
