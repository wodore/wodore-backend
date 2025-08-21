"""
This file contains a definition for Content-Security-Policy headers.

Read more about it:
https://developer.mozilla.org/ru/docs/Web/HTTP/Headers/Content-Security-Policy

We are using `django-csp` to provide these headers.
Docs: https://github.com/mozilla/django-csp
"""

# These values might and will be redefined in `development.py` env:
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "connect-src": ("'self'",),
        "default-src": ("'none'",),
        "font-src": (
            "'self'",
            "https://fonts.googleapis.com",
            "https://fonts.gstatic.com",
        ),
        "img-src": ("'self'", "data:", "https:", "http:", "data:"),
        "script-src": (
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
            "https://cdn.jsdelivr.net",
            "https://unpkg.com",
        ),
        "style-src": (
            "'self'",
            "'unsafe-inline'",
            "https://fonts.googleapis.com",
            "https://cdn.jsdelivr.net",
            "https://unpkg.com",
        ),
    }
}
