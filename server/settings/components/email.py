"""
This file contains a definition for Content-Security-Policy headers.

Read more about it:
https://developer.mozilla.org/ru/docs/Web/HTTP/Headers/Content-Security-Policy

We are using `django-csp` to provide these headers.
Docs: https://github.com/mozilla/django-csp
"""

from server.settings.components import config

ADMINS = [[x.replace(">", "").strip() for x in a.split("<")] for a in config("ADMINS").split(",")]
SERVER_EMAIL = config("SERVER_EMAIL")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL")
EMAIL_HOST = config("EMAIL_HOST")
EMAIL_PORT = config("EMAIL_PORT")
EMAIL_HOST_USER = config("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD")
EMAIL_USE_SSL = bool(int(config("EMAIL_USE_SSL")))
EMAIL_USE_TLS = bool(int(config("EMAIL_USE_TLS")))
