from typing import Any

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
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
    """Basemap style compare + FPS page.

    Access control:
    - development (DEBUG=True): open, no auth
    - staging (DEMOS_ENABLED=True, DEBUG=False): superuser only,
      redirects to the admin login if not authenticated
    - production: 404 (app not registered, URLs not included)
    """

    if settings.DEBUG:
        return render(request, "demos/mapcompare.html")

    # Non-DEBUG (staging): require superuser
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect_to_login(request.get_full_path())

    return render(request, "demos/mapcompare.html")
