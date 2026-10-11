from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def _widen_csp(view: Any) -> Any:
    """Apply the CSP widening only when the decorator is importable.

    django-csp is a production dependency, but the decorator import is
    deferred so plain-Python tooling (mypy, ruff) works without Django
    settings configured.
    """
    try:
        from csp.decorators import csp_update
    except ModuleNotFoundError:
        return view
    return csp_update({"connect-src": ["https:", "http:"]})(view)


@_widen_csp
def mapcompare(request: HttpRequest) -> HttpResponse:
    """Basemap style compare + FPS page (dev-only).

    Belt-and-braces: the URLs are only included when DEBUG is on, but the
    view double-checks so a misconfigured include can never leak the demo
    to a non-DEBUG deployment. The CSP decorator widens connect-src to
    any tileserver the user enters (acceptable: dev-only, triple-gated).
    """

    if not settings.DEBUG:
        from django.http import Http404

        raise Http404
    return render(request, "demos/mapcompare.html")
