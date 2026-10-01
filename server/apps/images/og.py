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

# Photo variant — same preset the JSON detail endpoint calls "large".
OG_PHOTO_SIZE = "1800x1200"

# Generated card — the recommended social preview aspect ratio.
OG_CARD_SIZE = "1200x630"

# Logo watermark on photos (SVG via the frontend host; PNG alternatives
# in public/logos/ of the frontend repo).
OG_LOGO_URL_PATH = "logos/wodore_original.svg"


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
        # Nested path rasterizes the 42px SVG logo up to ~160px before
        # compositing; alpha 15 = slightly faded.
        _composite_image(_frontend(OG_LOGO_URL_PATH), 160, "left-40", "bottom-40", 15),
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
