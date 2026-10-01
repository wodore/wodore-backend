"""Social preview (og:image) URLs, generated with imagor.

Two variants:

* ``og_photo_url`` — a real photo, resized to the 'large' preset
  (1800x1200, focal-aware) exactly like the JSON detail endpoint.
* ``og_card_url`` — a generated card for entities without a usable
  photo: the brand map background darkened for contrast, the app icon
  as a semi-transparent watermark, and the entity name in the BRAND
  FONT (Barlow Semi Condensed SemiBold) at the bottom.

Imagor requirements, verified live (see docker-compose.yml):

* ≥ v1.9 — the ``text()`` filter signature changed to
  ``text(text, x, y[, font[, color[...]]])`` with keyword/percent
  positioning and Pango font descriptions (hyphen-separated, size
  included: ``Barlow-Semi-Condensed-SemiBold-72``).
* Fonts must be mounted into the container — without any font,
  ``text()`` silently renders nothing. The brand TTF lives in
  ``docker/imagor/fonts/`` (OFL license alongside).
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings

from .transfomer import ImagorImage

# Photo variant — same preset the JSON detail endpoint calls "large".
OG_PHOTO_SIZE = "1800x1200"

# Generated card — the recommended social preview aspect ratio.
OG_CARD_SIZE = "1200x630"

# Brand font (Pango description without the size suffix, hyphenated).
OG_CARD_FONT = "Barlow-Semi-Condensed-SemiBold"

# Font sizes by combined text length (no wrapping: shrink instead).
_TEXT_SIZES = ((28, 72), (42, 56), (10_000, 40))


def _frontend(path: str) -> str:
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{path.lstrip('/')}"


def og_photo_url(image_url: str, focal: dict | None = None) -> str:
    """Signed imagor URL for a photo at the og:image size."""
    focal_str = None
    crop_start = crop_stop = None
    if focal:
        focal_str = f"{focal['x1']}x{focal['y1']}:{focal['x2']}x{focal['y2']}"
        crop_start, crop_stop = focal_str.split(":")
    return (
        ImagorImage(image_url)
        .transform(
            size=OG_PHOTO_SIZE,
            focal=focal_str,
            crop_start=crop_start,
            crop_stop=crop_stop,
        )
        .get_full_url()
    )


def og_card_url(title: str, subtitle: str | None = None) -> str:
    """Signed imagor URL for a generated brand card with the title."""
    text = f"{title} · {subtitle}" if subtitle else title
    size = next(size for max_len, size in _TEXT_SIZES if len(text) <= max_len)
    filters = [
        "brightness(-30)",
        # NOTE: the watermark URL stays RAW — the transformer encodes the
        # whole filter path, pre-encoding it here would double-encode.
        f"watermark({_frontend('icons/icon-512x512.png')},center,center,25,100)",
        f"text({quote(text)},center,-60,{OG_CARD_FONT}-{size},ffffff)",
    ]
    return (
        ImagorImage(_frontend("meta/meta.jpg"))
        .transform(size=OG_CARD_SIZE, filters=filters)
        .get_full_url()
    )
