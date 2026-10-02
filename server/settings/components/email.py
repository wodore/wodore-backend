"""
This file contains a definition for Content-Security-Policy headers.

Read more about it:
https://developer.mozilla.org/ru/docs/Web/HTTP/Headers/Content-Security-Policy

We are using `django-csp` to provide these headers.
Docs: https://github.com/mozilla/django-csp
"""

from server.settings.components import config


def parse_admin_emails(raw: str) -> list[list[str, str]]:
    """Parse ``Name <address>`` entries into ``[name, address]`` pairs.

    Robust against the configurations seen in the wild: empty string
    (CI), bare addresses and empty comma slots must not produce
    malformed pairs — ``[entry[1] for entry in ...]`` consumers (admin
    email in feedbacks) indexed past short entries and raised
    IndexError whenever a feedback actually sent mail without the env
    var set (CI test runs since the throttling test posts successfully)."""
    pairs: list[list[str, str]] = []
    for entry in raw.split(","):
        parts = [part.replace(">", "").strip() for part in entry.split("<")]
        if len(parts) == 2 and parts[1]:
            pairs.append(parts)
        elif len(parts) == 1 and parts[0]:
            pairs.append(["", parts[0]])
    return pairs


DJANGO_ADMIN_EMAILS = parse_admin_emails(config("DJANGO_ADMIN_EMAILS", ""))
SERVER_EMAIL = config("EMAIL_ADMIN_FROM_EMAIL", "")
DEFAULT_FROM_EMAIL = config("EMAIL_DEFAULT_FROM_EMAIL", "")
EMAIL_HOST = config("EMAIL_HOST", "")
EMAIL_PORT = config("EMAIL_PORT", "")
EMAIL_HOST_USER = config("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = bool(int(config("EMAIL_USE_SSL", "0")))
EMAIL_USE_TLS = bool(int(config("EMAIL_USE_TLS", "0")))
