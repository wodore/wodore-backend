"""
This file contains all the settings used in production.

This file is required and if development.py is present these
values are overridden.
"""

from server.settings.components.caches import CACHES
from server.settings.components.common import DJANGO_TRUSTED_DOMAINS, MIDDLEWARE
from server.settings.components.oidc import (
    ZITADEL_RP_ENABLED,
)

# Throttle counters must be shared across workers (openspec: api-throttling):
# LocMem would keep per-process limits (multiplied by worker count). The
# table is created by the no-args `app createcachetable` (idempotent).
CACHES["throttling"] = {
    "BACKEND": "django.core.cache.backends.db.DatabaseCache",
    "LOCATION": "django_cache_throttling",
    "TIMEOUT": 3600,
    "OPTIONS": {
        "MAX_ENTRIES": 100000,  # day-window keys expire after 24 h; steady
        # state ~= distinct daily client IPs, well under the cap
    },
}

# Production flags:
# https://docs.djangoproject.com/en/4.2/howto/deployment/

ENVIRONMENT = "production"

DEBUG = False

ALLOWED_HOSTS = [
    *DJANGO_TRUSTED_DOMAINS,
    # TODO: check production hosts
    # config("DOMAIN_NAME"),
    # We need this value for `healthcheck` to work:
    "localhost",
]


# Staticfiles
# https://docs.djangoproject.com/en/4.2/ref/contrib/staticfiles/

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

_PASS = "django.contrib.auth.password_validation"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"{_PASS}.UserAttributeSimilarityValidator"},
    {"NAME": f"{_PASS}.MinimumLengthValidator"},
    {"NAME": f"{_PASS}.CommonPasswordValidator"},
    {"NAME": f"{_PASS}.NumericPasswordValidator"},
]


# Security
# https://docs.djangoproject.com/en/4.2/topics/security/

SECURE_HSTS_SECONDS = 31536000  # the same as Caddy has
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
##
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
## SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [
    # This is required for healthcheck to work:
    "^health/",
]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CORS_ALLOWED_ORIGIN_REGEXES = [
    *[f"^https?://{d}" for d in DJANGO_TRUSTED_DOMAINS],
]

# Zitadel RP mode only (AUTH_PROVIDER=zitadel): refresh OIDC sessions.

if ZITADEL_RP_ENABLED:
    MIDDLEWARE += (
        "server.middleware.oidc.AsyncSafeSessionRefresh",  # pyright: ignore[reportUndefinedVariable]
    )
