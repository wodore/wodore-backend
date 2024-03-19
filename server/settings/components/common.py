"""
Django settings for server project.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their config, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

import typing as t
from typing import Dict, List, Tuple, Union

from corsheaders.defaults import default_headers
from hut_services import SERVICES, BaseService, OsmService, RefugesInfoService
from pydantic import BaseModel

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

SECRET_KEY = config("DJANGO_SECRET_KEY")

DOMAIN_NAMES = [d.strip() for d in config("DOMAIN_NAMES").split(",")] if config("DOMAIN_NAMES") else []
DEV_DOMAIN_NAMES = [d.strip() for d in config("DEV_DOMAIN_NAMES").split(",")] if config("DEV_DOMAIN_NAMES") else []
FRONTEND_DOMAIN = config("FRONTEND_DOMAIN") if config("FRONTEND_DOMAIN") else "http://localhost:9000"

# Application definition:

INSTALLED_APPS: Tuple[str, ...] = (
    # my server core:
    "server.core",
    # my apps:
    "server.apps.manager",
    "server.apps.main",
    "server.apps.organizations",
    "server.apps.contacts",
    "server.apps.owners",
    "server.apps.huts",
    # Extension:
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
    # Default django apps:
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    # django-admin:
    # "admin_volt.apps.AdminVoltConfig",  # https://github.com/app-generator/django-admin-volt
    # "grappelli",  # https://django-grappelli.readthedocs.io/en/latest/
    # "admin_interface",  # https://github.com/fabiocaccamo/django-admin-interface
    "unfold",  # https://github.com/unfoldadmin/django-unfold
    "unfold.contrib.filters",  # optional, if special filters are needed
    "unfold.contrib.forms",  # optional, if special form elements are needed
    # "unfold.contrib.import_export",  # optional, if django-import-export package is used
    # "unfold.contrib.guardian",  # optional, if django-guardian package is used
    # "unfold.contrib.simple_history",  # optional, if django-simple-history package is used
    "django.contrib.admin",
    "django.contrib.admindocs",
    # Security:
    "axes",
    "mozilla_django_oidc",  # Load after auth https://github.com/mozilla/mozilla-django-oidc
    # Health checks:
    # You may want to enable other checks as well,
    # see: https://github.com/KristianOellegaard/django-health-check
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
)

MIDDLEWARE: Tuple[str, ...] = (
    # Logging:
    "server.settings.components.logging.LoggingContextVarsMiddleware",
    # Cross-Origin Resource Sharing (CORS)
    "corsheaders.middleware.CorsMiddleware",
    # Content Security Policy:
    "csp.middleware.CSPMiddleware",
    # Django:
    "django.middleware.security.SecurityMiddleware",
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
    "mozilla_django_oidc.middleware.SessionRefresh",
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
        # "ENGINE": "django.db.backends.postgresql",
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("DJANGO_DATABASE_HOST"),
        "PORT": config("DJANGO_DATABASE_PORT", cast=int),
        "CONN_MAX_AGE": config("CONN_MAX_AGE", cast=int, default=60),
        "OPTIONS": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=15000ms",
        },
    },
    # "default": {
    #     "ENGINE": "django.db.backends.mysql",
    #     "NAME": config("POSTGRES_DB"),
    #     "USER": config("POSTGRES_USER"),
    #     "PASSWORD": config("POSTGRES_PASSWORD"),
    #     "HOST": config("DJANGO_DATABASE_HOST"),
    #     "PORT": config("DJANGO_DATABASE_PORT", cast=int),
    #     # "CONN_MAX_AGE": config("CONN_MAX_AGE", cast=int, default=60),
    #     "OPTIONS": {
    #         # "init_command": "SET GLOBAL MAX_EXECUTION_TIME = 3600",
    #         "connect_timeout": 10,
    #         # "max_statement_time": 10,
    #         # "options": "-c statement_timeout=15000ms",
    #         # "options": "-c max_execution_time=15000ms",
    #     },
    # },
    # "default": {
    #    "ENGINE": "django.db.backends.sqlite3",
    #    "NAME": BASE_DIR / "db.sqlite3",
    # }
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
# SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SOCIAL_AUTH_REDIRECT_IS_HTTPS = True


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

DEEPL_KEY = config("DEEPL_KEY")
