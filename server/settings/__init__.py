"""
This is a django-split-settings main file.

For more information read this:
https://github.com/sobolevn/django-split-settings
https://sobolevn.me/2017/04/managing-djangos-settings

To change settings file:
`DJANGO_ENV=production python manage.py runserver`
"""

import sys
from os import environ

try:
    import django_stubs_ext

    # Monkeypatching Django, so stubs will work for all generics,
    # see: https://github.com/typeddjango/django-stubs
    django_stubs_ext.monkeypatch()
except ModuleNotFoundError:
    pass

from split_settings.tools import include, optional

# Managing environment via `DJANGO_ENV` variable:
#
# Under pytest, default to "test": pytest-django builds Django settings
# during plugin init (before any conftest code runs), so a conftest-level
# pin is too late. Without this guard, a local `pytest` invocation with
# DJANGO_ENV unset loads the development environment and its
# debug-toolbar middleware into test responses (toolbar rendering then
# fails reversing djdt:* URLs, which only exist when DEBUG=True).
# An explicit DJANGO_ENV always wins (CI sets it in the workflow env).
if "pytest" in sys.modules:
    environ.setdefault("DJANGO_ENV", "test")
else:
    environ.setdefault("DJANGO_ENV", "development")
_ENV = environ["DJANGO_ENV"]

_base_settings = (
    "components/common.py",
    "components/logging.py",
    "components/csp.py",
    "components/unfold.py",
    "components/caches.py",
    "components/throttling.py",
    "components/oidc.py",
    "components/auth_local.py",
    "components/email.py",
    # dmr (django-modern-rest) base settings (response validation is
    # disabled for production inside the component):
    "components/dmr.py",
    # Select the right env:
    f"environments/{_ENV}.py",
    # Optionally override some settings:
    optional("environments/local.py"),
    # Conditional app/backend registrations - MUST load last, after the
    # environment files have re-imported the base tuples from common:
    "components/registry.py",
)

# Include settings:
include(*_base_settings)
