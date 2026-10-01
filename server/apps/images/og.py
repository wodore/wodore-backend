"""Social preview (og:image) URLs, generated with imagor.

Two variants:

* ``og_photo_url`` — a real photo, resized to the 'large' preset
  (1800x1200, focal-aware) exactly like the JSON detail endpoint.
* ``og_card_url`` — a generated card for entities without a usable
  photo: the brand background (which carries the Wodore logo) with the
  entity name drawn on top via imagor's ``text()`` filter. Verified
  against the local imagor: the text argument must be URL-encoded.
"""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings

from .transfomer import ImagorImage

# Photo variant — same preset the JSON detail endpoint calls "large".
OG_PHOTO_SIZE = "1800x1200"

# Generated card — the recommended social preview aspect ratio.
OG_CARD_SIZE = "1200x630"


def _og_card_background() -> str:
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/meta/meta.jpg"


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
    """Signed imagor URL for a generated card: brand background + title.

    The text arguments are URL-encoded (imagor requirement — a raw space
    makes the whole URL invalid). Text is drawn in white; the subtitle
    (e.g. elevation) is smaller, below the title.
    """
    filters = [f"text({quote(title)},56,ffffff,south)"]
    if subtitle:
        filters.append(f"text({quote(subtitle)},32,ffffff,south)")
    return (
        ImagorImage(_og_card_background())
        .transform(size=OG_CARD_SIZE, filters=filters)
        .get_full_url()
    )
