"""
Middleware for adding environment and SEO-related headers.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class EnvironmentHeadersMiddleware:
    """
    Middleware that adds environment identification header to all responses.

    Headers added:
        X-Environment: production|staging|development - Identify the environment
    """

    def __init__(self, get_response):
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


class RobotsTagMiddleware:
    """
    Middleware that adds X-Robots-Tag header to prevent search engine indexing.

    Headers added:
        X-Robots-Tag: noindex, nofollow - Prevent search engine indexing

    This is typically used in staging/development environments to prevent
    accidental indexing. Can also be used in production for API-only backends.
    """

    def __init__(self, get_response):
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
