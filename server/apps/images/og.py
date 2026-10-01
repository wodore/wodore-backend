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

from django.conf import settings

from .transfomer import ImagorImage

# Photo variant — 1200x630 (1.91:1): the og:image standard used by
# Facebook/WhatsApp/LinkedIn/X. Formerly 1800x1200 (3:2), which platforms
# center-crop vertically — risking the bottom-left logo.
OG_PHOTO_SIZE = "1200x630"

# Generated card — the same og:image aspect ratio.
OG_CARD_SIZE = "1200x630"

# Logo watermark on photos. The raster PNG (frontend public/logos/) is
# rendered at 800px from the SVG — vips' SVG rasterization composites
# visibly pixelated at watermark sizes, the PNG stays crisp.
OG_LOGO_URL_PATH = "logos/wodore_icon.png"
# Watermark geometry (owner-approved): 200px, horizontally centered,
# 33px below the bottom edge line (survives 1:1 center crops), fully
# opaque.
OG_LOGO_SIZE_PX = 200
OG_LOGO_POS = "center"
OG_LOGO_POS_Y = "bottom--33"
OG_LOGO_ALPHA = 0


def _frontend(path: str) -> str:
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{path.lstrip('/')}"


def _composite_image(source_url: str, size_px: int, x: str, y: str, alpha: int) -> str:
    """``image()`` filter string: pre-rasterize an SVG/overlay source to
    ``size_px`` via a nested unsafe path, then composite at x/y/alpha."""
    return f"image(/unsafe/{size_px}x{size_px}/{source_url},{x},{y},{alpha})"


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
