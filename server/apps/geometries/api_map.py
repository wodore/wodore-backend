"""Generic static-map endpoint for og:image cards.

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
"""

import re

from ninja import Query, Schema

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

from .api import router
from .models import GeoPlace

CACHE_SECONDS = 60 * 60
BASEMAPS = ("opentopomap",)


class StaticMapParams(Schema):
    lat: float | None = None
    lon: float | None = None
    place: str | None = None
    place_type: str | None = None
    zoom: int = CARD_ZOOM
    size: str = "1200x630"
    basemap: str = "opentopomap"
    marker: str | None = None
    marker_scale: float = 1.0
    effect: str = "none"
    attribution: bool = True
    offset: str = "0,0"
    v: str | None = None


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


@router.get("/map/static", include_in_schema=False, operation_id="get_static_map")
def get_static_map(
    request: HttpRequest, params: Query[StaticMapParams]
) -> HttpResponse:
    """Complete static-map og card (map + marker + watermark + effect)."""
    if params.basemap not in BASEMAPS or params.effect not in EFFECTS:
        raise Http404("Unknown basemap or effect.")
    if not 5 <= params.zoom <= 17:
        raise Http404("Zoom out of range.")
    size_match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", params.size)
    if size_match is None:
        raise Http404("Size must be WIDTHxHEIGHT (100-4000 px).")
    width, height = (int(g) for g in size_match.groups())
    if not (100 <= width <= 4000 and 100 <= height <= 4000):
        raise Http404("Size out of range.")

    if params.place:
        lat, lon, symbol_url = _resolve_place(params.place, params.place_type, request)
    elif params.lat is not None and params.lon is not None:
        lat, lon, symbol_url = params.lat, params.lon, None
    else:
        raise Http404("Provide lat/lon or place.")

    marker_mode = params.marker or ("symbol" if params.place else "none")

    offset_match = re.fullmatch(r"(-?\d{1,4}),(-?\d{1,4})", params.offset)
    if offset_match is None:
        raise Http404("Offset must be X,Y pixels.")
    offset_x, offset_y = (int(g) for g in offset_match.groups())

    name = static_map_cache_key(
        {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "zoom": params.zoom,
            "size": f"{width}x{height}",
            "basemap": params.basemap,
            "marker": marker_mode,
            "marker_scale": f"{params.marker_scale:g}",
            "effect": params.effect,
            "attribution": str(params.attribution).lower(),
            "offset": params.offset,
            "v": params.v,
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
            zoom=params.zoom,
            width=width,
            height=height,
            effect=params.effect,
            marker=marker_img,
            marker_scale=params.marker_scale,
            attribution=params.attribution,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        default_storage.save(name, ContentFile(data))
    with default_storage.open(name) as stored:
        data = stored.read()

    response = HttpResponse(data, content_type="image/jpeg")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return response
