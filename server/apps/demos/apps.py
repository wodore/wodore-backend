"""Development-only demo pages (spec: basemap-terrain consolidation, PR #292).

Hosts small interactive dev tools under ``/demos/`` — currently only
``/demos/mapcompare/`` (basemap style compare + FPS meter). The app is
registered in ``INSTALLED_APPS`` only in the development environment
(``server/settings/environments/development.py``) and the URLs are included
only when ``settings.DEBUG`` is true; the view additionally raises
``Http404`` unless ``DEBUG`` — nothing demo-shaped reaches staging/prod.
"""

from django.apps import AppConfig


class DemosConfig(AppConfig):
    name = "server.apps.demos"
    verbose_name = "Dev demos"
    default_auto_field = "django.db.models.BigAutoField"
