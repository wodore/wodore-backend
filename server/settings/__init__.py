"""
This is a django-split-settings main file.

For more information read this:
https://github.com/sobolevn/django-split-settings
https://sobolevn.me/2017/04/managing-djangos-settings

To change settings file:
`DJANGO_ENV=production python manage.py runserver`
"""

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
environ.setdefault("DJANGO_ENV", "development")
_ENV = environ["DJANGO_ENV"]

_base_settings = (
    "components/common.py",
    "components/logging.py",
    "components/csp.py",
    "components/unfold.py",
    "components/caches.py",
    "components/oicd.py",
    "components/email.py",
    # Select the right env:
    f"environments/{_ENV}.py",
    # Optionally override some settings:
    optional("environments/local.py"),
)

# Include settings:
include(*_base_settings)
