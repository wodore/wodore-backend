"""Social preview (og:image) URLs, generated with imagor.

Two variants:

* ``og_photo_url`` — a real photo, resized to the 'large' preset
  (1800x1200, focal-aware) exactly like the JSON detail endpoint, with
  the Wodore logo watermarked bottom-left (icon only, per owner
  preference — switch OG_WATERMARK_PATH to the wordmark variant to
  include the "wodore" text; the messenger already shows
  title/description text next to the image).
* ``og_card_url`` — the branded default image (map + wordmark artwork,
  1200x630) for entities without a usable photo.

Imagor requirements, verified live (see docker-compose.yml):

* ≥ v1.9 (new ``text()``/``watermark()`` signatures with keyword
  positioning). The dev container runs v1.9.6; production must match.
* Raster watermark sources only — this imagor build has NO SVG loader:
  SVG watermark URLs succeed with HTTP 200 but silently render nothing.
  The wordmark PNGs live in the frontend repo (public/logos/), the
  brand font TTF in docker/imagor/fonts/ (OFL) for any future text
  use.
"""

from __future__ import annotations

from django.conf import settings

from .transfomer import ImagorImage

# Photo variant — same preset the JSON detail endpoint calls "large".
OG_PHOTO_SIZE = "1800x1200"

# Generated card — the recommended social preview aspect ratio.
OG_CARD_SIZE = "1200x630"

# Photo watermark: icon-only by default. Alternatives in the frontend
# repo (public/logos/): wodore_wordmark_white.png (icon + "wodore"
# text), wodore_icon.png (original colors, for light backgrounds).
OG_WATERMARK_PATH = "logos/wodore_icon_white.png"


def _frontend(path: str) -> str:
    return f"{settings.FRONTEND_DOMAIN.rstrip('/')}/{path.lstrip('/')}"


def og_photo_url(image_url: str, focal: dict | None = None) -> str:
    """Signed imagor URL for a photo at the og:image size, with the
    white Wodore wordmark watermarked bottom-left."""
    focal_str = None
    crop_start = crop_stop = None
    if focal:
        focal_str = f"{focal['x1']}x{focal['y1']}:{focal['x2']}x{focal['y2']}"
        crop_start, crop_stop = focal_str.split(":")
    filters = [
        # NOTE: the watermark URL stays RAW — the transformer encodes the
        # whole filter path, pre-encoding it here would double-encode.
        # x=40 (from left), y=-40 (from bottom), alpha 85 (15% faded),
        # w_ratio 9 (percent of the image width — icon only).
        f"watermark({_frontend(OG_WATERMARK_PATH)},40,-40,85,9)",
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


def og_card_url(title: str | None = None, subtitle: str | None = None) -> str:
    """Signed imagor URL for the branded default card.

    The default image (public/meta/meta.jpg) already carries the map and
    the wordmark artwork — no text is drawn (the link preview shows the
    entity name and description as text next to the image anyway).
    ``title``/``subtitle`` are accepted and ignored for API stability.
    """
    return (
        ImagorImage(_frontend("meta/meta.jpg"))
        .transform(size=OG_CARD_SIZE)
        .get_full_url()
    )
