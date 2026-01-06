"""
This file contains all the settings used in production.

This file is required and if development.py is present these
values are overridden.
"""

from server.settings.components.common import DJANGO_TRUSTED_DOMAINS, MIDDLEWARE
from server.settings.components.oicd import discovery_info

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

if discovery_info:  # use only if setup correct
    MIDDLEWARE += ("mozilla_django_oidc.middleware.SessionRefresh",)

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
