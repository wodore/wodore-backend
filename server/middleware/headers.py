"""
Middleware for adding environment and SEO-related headers.
"""

import re
import typing as t

from django.conf import settings
from django.http import HttpRequest, HttpResponse

# The whole llms.txt family: the bare root, every settings-driven
# /llms.<lang>.txt variant, AND the permanent-redirect responses for
# unknown spellings (server/urls.py routes the catch-all to
# llms_txt_redirect) — all of them are language-fixed per URL, so none
# of them may carry a negotiation Vary.
_LLMS_PATH_RE = re.compile(r"^/llms(?:\.[^/]+)?\.txt$")


class EnvironmentHeadersMiddleware:
    """
    Middleware that adds environment identification header to all responses.

    Headers added:
        X-Environment: production|staging|development - Identify the environment
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and add headers to the response.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response with environment header added
        """
        response = self.get_response(request)

        # Add X-Environment header to identify environment
        environment = getattr(settings, "ENVIRONMENT", "unknown")
        response["X-Environment"] = environment

        return response


class LlmsTxtCacheMiddleware:
    """
    Middleware that makes the llms.txt documents safely CDN-cacheable.

    ``django.middleware.locale.LocaleMiddleware`` negotiates the active
    language from Accept-Language and stamps ``Vary: Accept-Language``
    onto every response it processes — including the llms.txt
    documents, whose language is fixed by URL (there is nothing to
    negotiate). The CDN does not vary its cache on Accept-Language, so
    that header would at best split caches and at worst make the
    responses look negotiable when they are not.

    Registered BEFORE LocaleMiddleware (outer in the response phase),
    this middleware therefore strips the Vary header again for exactly
    the llms.txt paths — every other response keeps it.

    Headers affected:
        Vary - removed on /llms.txt, its per-language variants and
        their unknown-spelling redirects
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and fix the Vary header for llms.txt paths.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response without a Vary header on llms.txt paths
        """
        response = self.get_response(request)

        if _LLMS_PATH_RE.fullmatch(request.path):
            response.headers.pop("Vary", None)

        return response


class RobotsTagMiddleware:
    """
    Middleware that adds X-Robots-Tag header to prevent search engine indexing.

    Headers added:
        X-Robots-Tag: noindex, nofollow - Prevent search engine indexing

    This is typically used in staging/development environments to prevent
    accidental indexing. Can also be used in production for API-only backends.
    """

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: Next middleware or view in the chain
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """
        Process the request and add headers to the response.

        Args:
            request: The HTTP request object

        Returns:
            HTTP response with X-Robots-Tag header added
        """
        response = self.get_response(request)

        # Add X-Robots-Tag header to prevent indexing
        response["X-Robots-Tag"] = "noindex, nofollow"

        return response
