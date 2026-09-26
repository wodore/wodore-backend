"""Compatibility views for the built-in OIDC provider.

django-oauth-toolkit (mounted under ``/oauth/local/`` from this app's urls)
serves discovery, authorize, token, userinfo and JWKS. What it does not
serve is ``end_session`` — this thin view keeps the frontend's logout URL
stable (clears the Django session and redirects).
"""

import logging

from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


@require_GET
def end_session(request: HttpRequest) -> HttpResponse:
    """RP-initiated logout: clear the session, redirect to a safe target."""
    post_logout = request.GET.get("post_logout_redirect_uri", "")
    if not _is_http_url(post_logout):
        post_logout = "/"
    logout(request)
    logger.info("local_auth: session ended (end_session)")
    return redirect(post_logout)
