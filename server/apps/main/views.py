from os import environ

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def index(request: HttpRequest) -> HttpResponse:
    """
    Main (or index) view.

    Returns rendered default page to the user.
    Typed with the help of ``django-stubs`` project.
    """
    return render(request, "main/index.html")


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


def llms_txt(request: HttpRequest) -> HttpResponse:
    """llms.txt (llmstxt.org): a markdown entry point for LLM agents.

    The frontend proxies wodore.com/llms.txt here. Absolute links are
    built from the request host (API) and ``FRONTEND_DOMAIN`` (web app).
    """
    return render(
        request,
        "txt/llms.txt",
        {
            "api_base": request.build_absolute_uri("/").rstrip("/"),
            "frontend_url": settings.FRONTEND_DOMAIN.rstrip("/"),
        },
        content_type="text/plain; charset=utf-8",
    )
