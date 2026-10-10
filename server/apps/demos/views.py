from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def mapcompare(request: HttpRequest) -> HttpResponse:
    """Basemap style compare + FPS page (dev-only).

    Belt-and-braces: the URLs are only included when DEBUG is on, but the
    view double-checks so a misconfigured include can never leak the demo
    to a non-DEBUG deployment.
    """

    if not settings.DEBUG:
        from django.http import Http404

        raise Http404
    return render(request, "demos/mapcompare.html")
