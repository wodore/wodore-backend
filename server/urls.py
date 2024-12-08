"""
Main URL mapping configuration file.

Include other URLConfs from external apps using method `include()`.

It is also a good practice to keep a single URL to the root index page.

This examples uses Django's default media
files serving technique in development.
"""

from health_check import urls as health_urls

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admindocs import urls as admindocs_urls
from django.contrib.staticfiles import handlers
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView
from django.views.static import serve

from .apps.api.api_v1 import api as api_v1
from .apps.main import urls as django_admin_urls
from .apps.main.views import index

admin.autodiscover()

urlpatterns = [
    # Auth
    path("oidc/", include("mozilla_django_oidc.urls")),
    # Apps:
    path("main/", include(django_admin_urls, namespace="main")),
    # Health checks:
    path("health/", include(health_urls)),
    # Locale:
    path("i18n/", include("django.conf.urls.i18n")),
    # django-admin:
    # path("grappelli/", include("grappelli.urls")),  # grappelli URLS
    # path("", include("admin_volt.urls")), # admin-volt
    path("admin/doc/", include(admindocs_urls)),
    # admin hack, should not be needed (https://stackoverflow.com/questions/59881651/django-mozilla-django-oidc-and-admin)
    path("admin/login/", RedirectView.as_view(url="/oidc/authenticate?next=/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    # Api:
    path("v1/", api_v1.urls),  # type: ignore
    # Text and xml static files:
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="txt/robots.txt",
            content_type="text/plain",
        ),
    ),
    path(
        "humans.txt",
        TemplateView.as_view(
            template_name="txt/humans.txt",
            content_type="text/plain",
        ),
    ),
    path("i18n/", include("django.conf.urls.i18n")),
    # It is a good practice to have explicit index view:
    path("", index, name="index"),
]

if settings.DEBUG:  # pragma: no cover
    import debug_toolbar

    urlpatterns = [
        # URLs specific only to django-debug-toolbar:
        path("__debug__/", include(debug_toolbar.urls)),
        *urlpatterns,
        # Serving media files in development only:
        # *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        # *staticfiles_urlpatterns(),
    ]
