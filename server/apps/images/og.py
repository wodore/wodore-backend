"""Social preview (og:image) URLs, generated with imagor.

Two variants:

* ``og_photo_url`` — a real photo, resized to the 'large' preset
  (1800x1200, focal-aware) exactly like the JSON detail endpoint, with
  the Wodore logo (SVG, original colors) composited bottom-left.
* ``og_card_url`` — the branded default card for entities without a
  usable photo: the brand map image (1200x630) with the entity's type
  symbol (SVG pictogram) composited large and centered.

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

from .transfomer import ImagorImage

if TYPE_CHECKING:
    from .models import Image

# Photo variant — 1200x630 (1.91:1): the og:image standard used by
# Facebook/WhatsApp/LinkedIn/X. Formerly 1800x1200 (3:2), which platforms
# center-crop vertically — risking the bottom-left logo.
OG_PHOTO_SIZE = "1200x630"

# Generated card — the same og:image aspect ratio.
OG_CARD_SIZE = "1200x630"

# Logo watermark on photos: the official watermark PNG in the frontend's
# public/meta/ (next to meta.jpg), served from wodore.com/meta/.
OG_LOGO_URL_PATH = "meta/wodore_watermark.png"
# Watermark geometry (owner-approved): 270px raster, horizontally
# centered, 10px from the bottom (survives 1:1 center crops), fully
# opaque.
OG_LOGO_SIZE_PX = 270
OG_LOGO_POS = "center"
OG_LOGO_POS_Y = "bottom-10"
OG_LOGO_ALPHA = 0

# Static-map og cards (hut/place meta fallbacks): render with the
# spotlight effect (desaturated blurred map behind the sharp rounded
# inset) and the type-symbol marker at 0.8x — owner-approved preview
# look. Both are plain query params on /v1/geo/map/static and part of
# its render cache key, so existing cards re-render on URL change.
OG_MAP_EFFECT = "spotlight"
OG_MAP_MARKER_SCALE = "0.8"

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
    if not source:
        return None
    if not source.startswith("http"):
        source = f"{settings.MEDIA_URL.rstrip('/')}/{source}"
    return source


def og_photo_url(image_url: str, focal: dict | None = None) -> str:
    """Signed imagor URL for a photo at the og:image size, with the
    Wodore logo composited bottom-left."""
    focal_str = None
    crop_start = crop_stop = None
    if focal:
        focal_str = f"{focal['x1']}x{focal['y1']}:{focal['x2']}x{focal['y2']}"
        crop_start, crop_stop = focal_str.split(":")
    filters = [
        _composite_image(
            _frontend(OG_LOGO_URL_PATH),
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


def og_map_card_url(map_url: str) -> str:
    """Signed imagor URL for a static-map og card: the generic
    static-map endpoint as source, with the Wodore watermark composited
    bottom-center — same geometry as the photo variant (horizontally
    centered survives WhatsApp's tighter center crops; the old
    left-of-center 0.18 was cut off in WhatsApp previews). The endpoint
    itself stays logo-free (also used directly by the image APIs)."""
    filters = [
        _composite_image(
            _frontend(OG_LOGO_URL_PATH),
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
