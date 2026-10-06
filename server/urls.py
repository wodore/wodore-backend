"""
Main URL mapping configuration file.

Include other URLConfs from external apps using method `include()`.

It is also a good practice to keep a single URL to the root index page.

This examples uses Django's default media
files serving technique in development.
"""

from dmr.routing import build_404_handler, build_500_handler
from health_check import Cache, Storage
from health_check.views import HealthCheckView

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admindocs import urls as admindocs_urls
from django.urls import include, path
from django.views.generic import TemplateView

from .apps.api import api_v1 as api_v1_module
from .apps.api import assets_view
from .apps.api.serializer import WodoreSerializer
from .apps.apiversions.docs import VersionedSwagger
from .apps.local_auth import account_views
from .apps.main import urls as django_admin_urls
from .apps.main import views as main_views
from .apps.main.views import index
from .core.db_health import PoolStatsDatabaseCheck

admin.autodiscover()

# API-style JSON errors for unknown /v1/* paths (found by the schemathesis
# contract run: Django's default HTML 404 violated the documented schema).
handler404 = build_404_handler("v1/", serializer=WodoreSerializer)
handler500 = build_500_handler("v1/", serializer=WodoreSerializer)

# Define base URL patterns
urlpatterns = [
    # Apps:
    path("main/", include(django_admin_urls, namespace="main")),
    # Health checks:
    # /health/ is the DEEP check (database + cache + storage) - use it for
    # readiness probes: "can this pod serve traffic right now?".
    path(
        "health/",
        HealthCheckView.as_view(
            checks=[
                (PoolStatsDatabaseCheck, {}),
                (Cache, {"cache_key": None}),
                (Storage, {}),
            ],
        ),
    ),
    # /health/live/ is the SHALLOW check - no dependencies at all. Use it
    # for k8s liveness probes: "is the process (and, under ASGI, the event
    # loop) alive?". A dependency check there would restart perfectly
    # healthy pods during a database hiccup (restart storm against an
    # already-struggling dependency).
    path("health/live/", HealthCheckView.as_view(checks=[])),
    # Locale:
    path("i18n/", include("django.conf.urls.i18n")),
    # django-admin:
    # path("grappelli/", include("grappelli.urls")),  # grappelli URLS
    # path("", include("admin_volt.urls")), # admin-volt
    path("admin/doc/", include(admindocs_urls)),
    path("admin/", admin.site.urls),
    # Api (django-modern-rest):
    # Version-addressable OpenAPI schema — exact path BEFORE the /v1/
    # include (serves stored snapshots for ?api_version=, live schema
    # otherwise).
    path("v1/openapi.json", api_v1_module.versioned_openapi_json),
    path("v1/docs", VersionedSwagger.as_view(api_v1_module._cached_schema())),
    *api_v1_module.urlpatterns,
    # Text and xml static files:
    path("robots.txt", main_views.robots_txt),
    path("llms.txt", main_views.llms_txt),
    # Backend-served brand assets (og/imagor pipeline references —
    # e.g. the watermark composited onto og photos). No frontend
    # dependency: the files are bundled in server/apps/api/assets/.
    path(
        "assets/logo/<str:name>",
        assets_view.serve_logo,
        name="logo-asset",
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

# Classic Zitadel relying-party routes (AUTH_PROVIDER=zitadel, the default
# outside dev/test): mozilla-django-oidc endpoints + the admin login
# redirect. #183 replaced the old OIDC_ENABLED block below with the
# allauth surface but dropped this one - without it /oidc/authenticate/
# is 404 and neither the admin SSO nor the SPA's Zitadel flow work.
# The admin-login bridge (in both provider blocks) preserves the
# deep-link ?next= target through to the provider's login page.
# Prepended, not appended: "admin/login/" must be matched BEFORE
# path("admin/", admin.site.urls) in the base list above, otherwise the
# admin site's own login form shadows the redirect and the admin silently
# falls back to the classic password form (regression introduced in #150).
if settings.ZITADEL_RP_ENABLED:
    urlpatterns = [
        path("oidc/", include("mozilla_django_oidc.urls")),
        path(
            "admin/login/",
            account_views.admin_login_redirect,
            {"login_path": "/oidc/authenticate"},
        ),
        *urlpatterns,
    ]

# Built-in OIDC provider (DOT) + account management (allauth): direct
# logins without a ?next= target land in the admin (LOGIN_REDIRECT_URL).
if settings.OIDC_ENABLED:
    urlpatterns = [
        path(
            "admin/login/",
            account_views.admin_login_redirect,
            {"login_path": "/accounts/login/"},
        ),
        path("oauth/local/", include("server.apps.local_auth.urls")),
        # Self-service account overview (exact match, before the allauth
        # include which serves all /accounts/<sub> flows).
        path("accounts/", account_views.account_overview),
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
