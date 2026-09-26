"""
Main URL mapping configuration file.

Include other URLConfs from external apps using method `include()`.

It is also a good practice to keep a single URL to the root index page.

This examples uses Django's default media
files serving technique in development.
"""

from health_check import Cache, Database, Storage
from health_check.views import HealthCheckView

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admindocs import urls as admindocs_urls
from django.urls import include, path
from django.views.generic import RedirectView, TemplateView

from .apps.api.api_v1 import api as api_v1
from .apps.main import urls as django_admin_urls
from .apps.main.views import index

admin.autodiscover()

# Define base URL patterns
urlpatterns = [
    # Apps:
    path("main/", include(django_admin_urls, namespace="main")),
    # Health checks:
    path(
        "health/",
        HealthCheckView.as_view(
            checks=[
                (Database, {}),
                (Cache, {"cache_key": None}),
                (Storage, {}),
            ],
        ),
    ),
    # Locale:
    path("i18n/", include("django.conf.urls.i18n")),
    # django-admin:
    # path("grappelli/", include("grappelli.urls")),  # grappelli URLS
    # path("", include("admin_volt.urls")), # admin-volt
    path("admin/doc/", include(admindocs_urls)),
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

# Built-in OIDC provider (DOT) + account management (allauth) + admin
# login redirect (only when OIDC is enabled; when disabled the admin falls
# back to Django's classic login form).
# Prepended, not appended: "admin/login/" must be matched BEFORE
# path("admin/", admin.site.urls) in the base list above, otherwise the
# admin site's own login form shadows the redirect and the admin silently
# falls back to the classic password form (regression introduced in #150).
if settings.OIDC_ENABLED:
    urlpatterns = [
        # Unified login (allauth); "?next=/admin/" so staff land in the
        # admin after signing in.
        path(
            "admin/login/",
            RedirectView.as_view(url="/accounts/login/?next=/admin/", permanent=False),
        ),
        path("oauth/local/", include("server.apps.local_auth.urls")),
        path("accounts/", include("allauth.urls")),
        *urlpatterns,
    ]

if settings.DEBUG:  # pragma: no cover
    try:
        import debug_toolbar

        urlpatterns = [
            # URLs specific only to django-debug-toolbar:
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
            # Serving media files in development only:
            *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
            *static(settings.STATIC_URL, document_root=settings.STATIC_ROOT),
        ]
    except ModuleNotFoundError:
        pass
