from os import environ

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

# Canonical production origin — the one every environment must advertise
# to LLM agents (see llms_txt below and the robots.txt template default).
_PRODUCTION_URL = "https://wodore.com"

# Language-fixed llms.txt URLs (see llms_txt below): the bare root is
# always the English document (the URL LLMs fetch by convention);
# German, French and Italian live at stable /llms.<lang>.txt variants.
# Shared with LlmsTxtCacheMiddleware (server/middleware/headers.py),
# which strips the Vary header LocaleMiddleware adds to these paths.
LLMS_LANGUAGE_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
}
LLMS_TXT_PATHS = frozenset(
    "/llms.txt" if lang == "en" else f"/llms.{lang}.txt" for lang in LLMS_LANGUAGE_NAMES
)

# Explicit cache policy for the llms.txt documents: public for the CDN,
# one hour fresh, then stale-while-revalidate for a day so agents keep
# being served (from cache) while the origin refreshes. Without this
# the CDN silently applies its own 1h default with no revalidation
# window.
LLMS_TXT_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


def index(request: HttpRequest) -> HttpResponse:
    """
    Main (or index) view.

    Returns rendered default page to the user.
    Typed with the help of ``django-stubs`` project.
    """
    return render(
        request,
        "main/index.html",
        # Same context pattern as robots.txt/llms.txt: the web-app link
        # follows FRONTEND_DOMAIN instead of a hardcoded production URL.
        {"frontend_url": settings.FRONTEND_DOMAIN.rstrip("/")},
    )


def robots_txt(request: HttpRequest) -> HttpResponse:
    """robots.txt for the API host.

    Production keeps the API out of search indexes but explicitly allows
    well-behaved AI crawlers on the public read-only data (see
    txt/robots.txt). Non-production environments (staging/preview) deny
    everything — they must not be findable.
    """
    return render(
        request,
        "txt/robots.txt",
        {
            # Not a Django setting: DJANGO_ENV is the plain env var the
            # settings loader keys on (see server/settings/__init__.py).
            "allow_ai_crawlers": environ.get("DJANGO_ENV", "development")
            == "production",
            "frontend_url": settings.FRONTEND_DOMAIN.rstrip("/"),
        },
        content_type="text/plain",
    )


def _llms_url(lang: str, base_url: str) -> str:
    """Stable URL of a language's llms.txt document on the public origin."""
    return f"{base_url}/llms.txt" if lang == "en" else f"{base_url}/llms.{lang}.txt"


def _llms_language_links(lang: str, base_url: str) -> str:
    """Header-block line linking every OTHER llms.txt language variant."""
    return ", ".join(
        f"{name}: {_llms_url(code, base_url)}"
        for code, name in LLMS_LANGUAGE_NAMES.items()
        if code != lang
    )


def llms_txt(request: HttpRequest, lang: str = "en") -> HttpResponse:
    """llms.txt (llmstxt.org): a markdown entry point for LLM agents.

    The frontend proxies wodore.com/llms.txt here. Absolute links are
    built from the request host (API) and ``FRONTEND_DOMAIN`` (web app).

    Every URL is language-fixed: the bare ``/llms.txt`` is always the
    English document (the entry point LLMs fetch by convention), while
    German/French/Italian live at stable ``/llms.<lang>.txt`` variants —
    each opening with links to the other languages. There is no
    Accept-Language negotiation: responses carry an explicit
    Cache-Control and no Vary (LlmsTxtCacheMiddleware strips the one
    LocaleMiddleware would add), so the CDN can cache them per URL.
    The body itself stays English in all variants until translations
    are wired — Content-Language says so honestly.

    Staging is different on purpose: staging hosts must never be
    advertised to LLM agents (robots.txt already disallows everything
    there), so the document leads with a notice pointing at production
    and every advertised URL — API links included — is the production
    one, regardless of request host or ``FRONTEND_DOMAIN``.
    """
    # Same env-detection as robots_txt: DJANGO_ENV is the plain env var
    # the settings loader keys on (see server/settings/__init__.py).
    is_staging = environ.get("DJANGO_ENV", "development") == "staging"
    frontend_url = (
        _PRODUCTION_URL if is_staging else settings.FRONTEND_DOMAIN.rstrip("/")
    )
    response = render(
        request,
        "txt/llms.txt",
        {
            "is_staging": is_staging,
            "api_base": _PRODUCTION_URL
            if is_staging
            else request.build_absolute_uri("/").rstrip("/"),
            "frontend_url": frontend_url,
            "language_links": _llms_language_links(lang, frontend_url),
        },
        content_type="text/plain; charset=utf-8",
    )
    response.headers["Cache-Control"] = LLMS_TXT_CACHE_CONTROL
    response.headers["Content-Language"] = "en"
    return response
