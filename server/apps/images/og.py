"""Social preview (og:image) URLs, generated with imagor.

Two variants:

* ``og_photo_url`` — a real photo at the og:image size (1200x630,
  focal-aware) with the Wodore logo composited at the bottom, a bit
  left of center.
* ``og_card_url`` — the branded default card for entities without a
  usable photo: the brand map image (1200x630) with the entity's type
  symbol (SVG pictogram) composited large and centered.

Static-map og cards are NOT generated here — the image service's
``static_map_fallback`` feature (``/v1/geo/map/static``, og dimensions,
watermark baked into the render) is the og fallback.

SVG compositing notes, verified live against imagor v1.9.6:

* ``watermark(svg_url, ...)`` silently ignores ``w_ratio`` — SVGs
  composite at their intrinsic size (the 42px logo) and are effectively
  invisible. Use the recursive ``image()`` filter instead: a nested
  imagor path pre-rasterizes the SVG to any size before compositing.
* ``image()`` supports offset keywords (``left-40``, ``bottom-40``),
  alpha (0 = opaque … 100 = transparent), and nested paths are fine
  inside signed parent URLs (no dpi() needed).
* The raster logo PNGs in the frontend repo (public/logos/) stay as an
  alternative — switch OG_LOGO_URL if a white/wordmark variant is
  wanted for dark photos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpRequest

from .transfomer import ImagorImage

if TYPE_CHECKING:
    from .models import Image

# Photo variant — 1200x630 (1.91:1): the og:image standard used by
# Facebook/WhatsApp/LinkedIn/X. Formerly 1800x1200 (3:2), which platforms
# center-crop vertically — risking the bottom-left logo.
OG_PHOTO_SIZE = "1200x630"

# Generated card — the same og:image aspect ratio.
OG_CARD_SIZE = "1200x630"

# Logo watermark on photos: served by the backend itself
# (/assets/logo/wodore_watermark.png — the bundled copy in
# server/apps/api/assets/, no frontend dependency), with the asset's
# content digest as ?v= so imagor results and CDN entries bust when
# the logo is replaced.
LOGO_ASSET_NAME = "wodore_watermark.png"
# Watermark geometry (owner-approved): 270px raster, a bit LEFT of
# center (0.33 of the free space — same position as the static-map
# cards), 10px from the bottom (survives 1:1 center crops), fully
# opaque.
OG_LOGO_SIZE_PX = 270
OG_LOGO_POS = "0.33"
OG_LOGO_POS_Y = "bottom-10"
OG_LOGO_ALPHA = 0

# Static-map og cards (hut/place meta fallbacks): render with the
# spotlight effect (warm sharp island under a cold, bokeh-blurred
# moonlight surround) and the type-symbol marker at 0.5x —
# owner-approved preview look. Both are plain query params on
# /v1/geo/map/static and part of its render cache key, so existing
# cards re-render on URL change.
OG_MAP_EFFECT = "spotlight"
OG_MAP_MARKER_SCALE = "0.5"

# Map cards render one zoom level out (15): huts sit in visible terrain
# context instead of a rooftop close-up.
OG_MAP_ZOOM = 15


def _frontend(path: str) -> str:
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{path.lstrip('/')}"


def _composite_image(source_url: str, size_px: int, x: str, y: str, alpha: int) -> str:
    """``image()`` filter string: pre-rasterize an SVG/overlay source to
    ``size_px`` via a nested unsafe path, then composite at x/y/alpha.

    The nested URL MUST be percent-encoded: a raw ``https://`` inside
    the filter contains ``//`` which nginx (ingress, merge_slashes on by
    default) collapses to ``/`` before the request reaches imagor —
    changing the bytes the signature was computed over and 403-ing the
    URL. Escaped, the path passes any proxy untouched and imagor
    unescapes the filter argument itself."""
    from urllib.parse import quote

    return f"image(/unsafe/{size_px}x{size_px}/{quote(source_url, safe='')},{x},{y},{alpha})"


def normalize_source(source: str) -> str | None:
    """Servable URL for a raw source string: media-relative paths get
    the media prefix, absolute URLs pass through.

    Returns ``None`` when the string is empty — an empty source would
    sign the bare imagor media alias (e.g. ``.../wd``) and 500 in
    imagor, so callers must skip to the next candidate or fall back."""
    if not source:
        return None
    if not source.startswith("http"):
        source = f"{settings.MEDIA_URL.rstrip('/')}/{source.lstrip('/')}"
    return source


def photo_source(image: Image) -> str | None:
    """Servable source URL for an :class:`Image` row: the local file when
    set, else the pinned external raw URL (pinned provider rows keep the
    file field empty and the origin URL in ``source_url_raw``).

    Returns ``None`` when the row has nothing servable — an empty source
    would sign the bare imagor media alias (e.g. ``.../wd``) and 500 in
    imagor, so callers must skip to the next candidate or fall back."""
    source = str(image.image) if image.image else ""
    if not source:
        source = image.source_url_raw or ""
    return normalize_source(source)


def watermark_url(request: HttpRequest | None = None) -> str:
    """Absolute URL of the backend-served watermark asset, with the
    asset's content digest as ``?v=`` (imagor result-cache busting).

    Built from the request when one is in scope (correct host behind
    any proxy), else from ``BACKEND_DOMAIN``."""
    from django.urls import reverse

    from server.apps.api.assets_view import logo_version

    path = reverse("logo-asset", args=[LOGO_ASSET_NAME])
    if request is not None:
        base = request.build_absolute_uri(path)
    else:
        base = f"{settings.BACKEND_DOMAIN.rstrip('/')}{path}"
    return f"{base}?v={logo_version()}"


def og_photo_url(
    image_url: str,
    focal: dict | None = None,
    *,
    request: HttpRequest | None = None,
) -> str:
    """Signed imagor URL for a photo at the og:image size, with the
    Wodore logo (backend-served, ``?v=``-busted) composited at the
    bottom, a bit left of center (same position as the static-map
    cards)."""
    focal_str = None
    crop_start = crop_stop = None
    if focal:
        focal_str = f"{focal['x1']}x{focal['y1']}:{focal['x2']}x{focal['y2']}"
        crop_start, crop_stop = focal_str.split(":")
    filters = [
        _composite_image(
            watermark_url(request),
            OG_LOGO_SIZE_PX,
            OG_LOGO_POS,
            OG_LOGO_POS_Y,
            OG_LOGO_ALPHA,
        ),
    ]
    return (
        ImagorImage(image_url)
        .transform(
            size=OG_PHOTO_SIZE,
            focal=focal_str,
            crop_start=crop_start,
            crop_stop=crop_stop,
            filters=filters,
        )
        .get_full_url()
    )


def og_map_card_url(map_url: str, *, request: HttpRequest | None = None) -> str:
    """Signed imagor URL for a static-map og card: the map endpoint's
    card (spotlight, marker, og dimensions — rendered by the backend)
    as the source, with the backend-served Wodore watermark
    (``?v=``-busted) composited at the bottom, a bit left of center."""
    filters = [
        _composite_image(
            watermark_url(request),
            OG_LOGO_SIZE_PX,
            OG_LOGO_POS,
            OG_LOGO_POS_Y,
            OG_LOGO_ALPHA,
        )
    ]
    return (
        ImagorImage(map_url)
        .transform(size=OG_CARD_SIZE, filters=filters)
        .get_full_url()
    )


def og_card_url(symbol_url: str | None = None) -> str:
    """Signed imagor URL for the branded default card, optionally with
    the entity's type symbol (SVG) composited large and centered."""
    filters = []
    if symbol_url:
        filters.append(_composite_image(symbol_url, 500, "center", "center", 20))
    return (
        ImagorImage(_frontend("meta/meta.jpg"))
        .transform(size=OG_CARD_SIZE, filters=filters)
        .get_full_url()
    )
