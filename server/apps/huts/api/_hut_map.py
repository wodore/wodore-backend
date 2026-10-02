"""Static map endpoint for og:image fallback cards.

``GET /v1/huts/{slug}/map.png`` — OpenTopoMap card centered on the hut,
rendered once per hut revision and stored via the default storage.
The URL stays stable; consumers (the hut meta endpoint / imagor) bust
their caches with ``?v=<modified>`` — any hut change therefore produces
a fresh map, ETag-style.
"""

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpRequest, HttpResponse

from server.apps.api.ogmap import render_static_map

from ..models import Hut
from ._router import router

CACHE_SECONDS = 60 * 60


def _map_png(slug: str, hut: Hut) -> bytes:
    """Render (once) and return the stored map PNG for this hut revision."""
    name = f"ogmaps/{slug}-{hut.modified:%Y%m%dT%H%M%S}.png"
    if not default_storage.exists(name):
        data = render_static_map(hut.location.y, hut.location.x)
        default_storage.save(name, ContentFile(data))
    with default_storage.open(name) as stored:
        return stored.read()


@router.get("/{slug}/map.png", include_in_schema=False, operation_id="get_hut_map")
def get_hut_map(request: HttpRequest, slug: str) -> HttpResponse:
    """OpenTopoMap static map centered on the hut (og:image fallback)."""
    hut = (
        Hut.objects.filter(is_active=True, is_public=True, slug=slug)
        .only("slug", "modified", "location")
        .first()
    )
    if hut is None or hut.location is None:
        msg = f"Could not find a place for '{slug}'."
        raise Http404(msg)
    response = HttpResponse(_map_png(slug, hut), content_type="image/png")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return response
