from os import environ

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import render
from django.utils import translation

# Canonical production origin — the one every environment must advertise
# to LLM agents (see llms_txt below and the robots.txt template default).
_PRODUCTION_URL = "https://wodore.com"

# The bare /llms.txt is ALWAYS the English document: the URL LLM agents
# fetch by convention (no Accept-Language negotiation). Every OTHER
# language in settings.LANGUAGES gets a stable /llms.<lang>.txt variant
# beside it — that setting is the single source of truth for the whole
# llms.txt family: the URL routes (server/urls.py), the robots.txt AI
# Allow lines and the cross-links header all derive from it.
LLMS_ROOT_LANG = "en"

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


def llms_language_names() -> dict[str, str]:
    """Language code → native name for the llms.txt family.

    The language list comes from ``settings.LANGUAGES`` (the one place
    languages are defined); the names are the NATIVE names from Django's
    own language metadata — stable per code, regardless of the active
    locale. Translating the ``LANGUAGES`` names instead would make the
    cross-links line change with the reader's language and defeat the
    per-URL CDN cache. Codes Django does not know fall back to the bare
    code.
    """
    names: dict[str, str] = {}
    for code, _name in settings.LANGUAGES:
        try:
            # Title-case: Django's name_local is lower-case for some
            # languages ("français", "italiano") while the llms header
            # line wants display names.
            local = translation.get_language_info(code)["name_local"]
            names[code] = local[:1].upper() + local[1:]
        except KeyError:
            names[code] = code
    return names


def llms_variant_paths() -> list[str]:
    """Per-language variant paths (``/llms.<lang>.txt``), settings-driven.

    The root language is excluded — it IS the bare ``/llms.txt``.
    """
    return [
        f"/llms.{code}.txt" for code in llms_language_names() if code != LLMS_ROOT_LANG
    ]


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
            # The per-language llms.txt Allow lines loop over these
            # (settings.LANGUAGES is the single source of truth).
            "llms_variant_paths": llms_variant_paths(),
        },
        content_type="text/plain",
    )


def _llms_url(lang: str, base_url: str) -> str:
    """Stable URL of a language's llms.txt document on the public origin."""
    return (
        f"{base_url}/llms.txt"
        if lang == LLMS_ROOT_LANG
        else f"{base_url}/llms.{lang}.txt"
    )


def _llms_language_links(lang: str, base_url: str) -> str:
    """Header-block line linking every OTHER llms.txt language variant."""
    return ", ".join(
        f"{name}: {_llms_url(code, base_url)}"
        for code, name in llms_language_names().items()
        if code != lang
    )


def llms_txt(request: HttpRequest, lang: str = LLMS_ROOT_LANG) -> HttpResponse:
    """llms.txt (llmstxt.org): a markdown entry point for LLM agents.

    The frontend proxies wodore.com/llms.txt here. Absolute links are
    built from the request host (API) and ``FRONTEND_DOMAIN`` (web app).

    Every URL is language-fixed: the bare ``/llms.txt`` is always the
    English document (the entry point LLMs fetch by convention), while
    the other languages from ``settings.LANGUAGES`` live at stable
    ``/llms.<lang>.txt`` variants — each opening with links to the other
    languages. There is no Accept-Language negotiation: responses carry
    an explicit Cache-Control and no Vary (LlmsTxtCacheMiddleware strips
    the one LocaleMiddleware would add), so the CDN can cache them per
    URL.

    The variant's locale drives the BODY (the template's ``{% translate %}``
    blocks render in it — see locale/<lang>/LC_MESSAGES/) and the
    Content-Language header alike; untranslated strings fall back to the
    English msgid, so a language added to ``settings.LANGUAGES`` before
    its catalog exists serves the English text under an honest
    Content-Language.

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
    codes = list(llms_language_names())
    # The URL's language wins over any request negotiation: render the
    # body with this locale active (and deactivate again right after).
    with translation.override(lang):
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
                # Language enumerations in the body prose (hut-page URL
                # pattern and the ?lang= parameter values) come from the
                # same settings-driven list — no hardcoded language list
                # in the template. blocktranslate cannot apply filters,
                # so precompute the joined forms.
                "lang_codes_csv": ", ".join(codes),
                "lang_codes_pipe": "|".join(codes),
            },
            content_type="text/plain; charset=utf-8",
        )
    response.headers["Cache-Control"] = LLMS_TXT_CACHE_CONTROL
    response.headers["Content-Language"] = lang
    return response


def llms_txt_redirect(request: HttpRequest, lang: str) -> HttpResponse:
    """Serve or permanently move /llms.<lang>.txt spellings the explicit
    routes do not cover.

    LLM agents invent variant URLs (/llms.es.txt, or the root language
    under its variant spelling /llms.en.txt). A spelling that names a
    NON-root language from settings.LANGUAGES serves the variant (the
    URL routes are generated from the same setting — this branch covers
    it whenever the urlconf lags behind, e.g. tests overriding the
    setting). Everything else — unknown languages, the root language in
    variant spelling — permanently redirects to the canonical English
    entry point instead of 404ing. A 301 (not 308) is enough: these
    documents are GET-only, so there is no request method to preserve.
    """
    if lang != LLMS_ROOT_LANG and lang in llms_language_names():
        return llms_txt(request, lang=lang)
    response = HttpResponsePermanentRedirect("/llms.txt")
    # Same CDN policy as the documents: a permanent redirect between
    # cacheable documents is itself safely cacheable.
    response.headers["Cache-Control"] = LLMS_TXT_CACHE_CONTROL
    return response
