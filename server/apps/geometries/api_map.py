"""Generic static-map endpoint for og:image cards (plain Django view).

``GET /v1/geo/map/static`` — parameters:

* ``lat``/``lon`` — center directly, or
* ``place`` (slug) + ``place_type`` (``hut`` | ``geoplace``; default:
  try geoplace, then hut) — center on the entity, and its type symbol
  becomes the marker automatically
* ``zoom`` (default 16)
* ``size`` (``WIDTHxHEIGHT``, default ``1200x630``, the og:image
  standard; everything on the card scales with it)
* ``basemap`` (``opentopomap``, the only one for now)
* ``marker`` (``symbol`` default when a place is given, ``none``)
* ``marker_scale`` (multiplier, default 1)
* ``effect`` (``none`` | ``blur_border`` | ``spotlight`` | ``vignette``
  | ``blurred_edges``)
* ``offset`` (``X,Y`` pixels, default ``0,0``) — shifts the map view:
  positive X moves the view right (the entity moves left on the card),
  positive Y moves the view down (entity moves up)
* ``attribution`` (default true — OpenTopoMap license requires it on
  published maps; opt out only for non-published uses)
* ``v`` — free-form cache buster (the caller's last-modified); any
  change produces a fresh render, ETag-style

The rendered card is complete (map + marker + watermark + effect +
attribution), stored once per parameter set via the default storage.
Hidden from the OpenAPI schema (binary response).
"""

import math
import re

from dmr.routing import external_path

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpRequest, HttpResponse

from server.apps.api.ogmap import (
    CARD_ZOOM,
    EFFECTS,
    fetch_marker,
    render_static_map,
    static_map_cache_key,
)
from server.apps.huts.models import Hut
from server.apps.symbols.utils import resolve_symbol_urls

from .models import GeoPlace

CACHE_SECONDS = 60 * 60
BASEMAPS = ("opentopomap",)


def _entity_symbol(entity, request: HttpRequest) -> str | None:
    """Detailed type-symbol URL for a hut (type) or geoplace (category)."""
    if isinstance(entity, Hut):
        if entity.hut_type_open is None:
            return None
        symbols = resolve_symbol_urls(entity.hut_type_open, {"request": request})
    else:
        category = (
            entity.categories.filter(is_active=True)
            .select_related("symbol_detailed")
            .first()
        )
        if category is None:
            return None
        symbols = resolve_symbol_urls(category, {"request": request})
    return symbols.get("detailed") if symbols else None


def _resolve_place(
    slug: str, place_type: str | None, request: HttpRequest
) -> tuple[float, float, str | None]:
    """Position + type symbol for a place/hut slug (geoplace first unless
    place_type is explicit)."""
    candidates = (
        ("hut",)
        if place_type == "hut"
        else ("geoplace",)
        if place_type == "geoplace"
        else ("geoplace", "hut")
    )
    for kind in candidates:
        if kind == "hut":
            hut = (
                Hut.objects.filter(is_active=True, is_public=True, slug=slug)
                .select_related("hut_type_open")
                .first()
            )
            if hut is not None and hut.location is not None:
                return hut.location.y, hut.location.x, _entity_symbol(hut, request)
        else:
            place = GeoPlace.objects.filter(
                is_active=True, is_public=True, slug=slug
            ).first()
            if place is not None and place.location is not None:
                return (
                    place.location.y,
                    place.location.x,
                    _entity_symbol(place, request),
                )
    msg = f"Could not find a place '{slug}'."
    raise Http404(msg)


def _get_float(request: HttpRequest, name: str) -> float | None:
    raw = request.GET.get(name)
    if raw is None:
        return None
    value = float(raw)
    if math.isnan(value):
        raise Http404(f"{name} must be a finite number.")
    return value


def get_static_map(request: HttpRequest) -> HttpResponse:
    """Complete static-map og card (map + marker + watermark + effect)."""
    basemap = request.GET.get("basemap", "opentopomap")
    effect = request.GET.get("effect", "none")
    if basemap not in BASEMAPS or effect not in EFFECTS:
        raise Http404("Unknown basemap or effect.")

    try:
        zoom = int(request.GET.get("zoom", CARD_ZOOM))
    except ValueError:
        raise Http404("Zoom must be an integer.") from None
    if not 5 <= zoom <= 17:
        raise Http404("Zoom out of range.")

    size_match = re.fullmatch(
        r"(\d{3,4})x(\d{3,4})", request.GET.get("size", "1200x630")
    )
    if size_match is None:
        raise Http404("Size must be WIDTHxHEIGHT (100-4000 px).")
    width, height = (int(g) for g in size_match.groups())
    if not (100 <= width <= 4000 and 100 <= height <= 4000):
        raise Http404("Size out of range.")

    place_slug = request.GET.get("place")
    lat = _get_float(request, "lat")
    lon = _get_float(request, "lon")
    if place_slug:
        lat, lon, symbol_url = _resolve_place(
            place_slug, request.GET.get("place_type"), request
        )
    elif lat is not None and lon is not None:
        symbol_url = None
    else:
        raise Http404("Provide lat/lon or place.")

    marker_mode = request.GET.get("marker") or ("symbol" if place_slug else "none")

    offset_raw = request.GET.get("offset", "0,0")
    offset_match = re.fullmatch(r"(-?\d{1,4}),(-?\d{1,4})", offset_raw)
    if offset_match is None:
        raise Http404("Offset must be X,Y pixels.")
    offset_x, offset_y = (int(g) for g in offset_match.groups())

    try:
        marker_scale = float(request.GET.get("marker_scale", "1.0"))
    except ValueError:
        raise Http404("marker_scale must be a number.") from None
    attribution = request.GET.get("attribution", "true").lower() != "false"

    name = static_map_cache_key(
        {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "zoom": zoom,
            "size": f"{width}x{height}",
            "basemap": basemap,
            "marker": marker_mode,
            "marker_scale": f"{marker_scale:g}",
            "effect": effect,
            "attribution": str(attribution).lower(),
            "offset": offset_raw,
            "v": request.GET.get("v"),
            "symbol": symbol_url,
        }
    )
    if not default_storage.exists(name):
        marker_img = (
            fetch_marker(symbol_url, 512)
            if marker_mode == "symbol" and symbol_url
            else None
        )
        data = render_static_map(
            lat,
            lon,
            zoom=zoom,
            width=width,
            height=height,
            effect=effect,
            marker=marker_img,
            marker_scale=marker_scale,
            attribution=attribution,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        default_storage.save(name, ContentFile(data))
    with default_storage.open(name) as stored:
        data = stored.read()

    response = HttpResponse(data, content_type="image/jpeg")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return response


paths = [
    external_path(
        "map/static",
        get_static_map,
        openapi=None,
        name="get_static_map",
    ),
]
