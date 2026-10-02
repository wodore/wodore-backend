"""Static-map card rendering for og:image fallbacks (OpenTopoMap).

Renders the COMPLETE card in Pillow: map canvas, optional marker (the
entity's type symbol raster), optional watermark, and optional visual
effects — callers get a final 1200x630 JPEG, no imagor compositing
needed (imagor is only used to rasterize symbol SVGs at render time).

Effects (``effect=`` parameter):

* ``none`` — plain map
* ``blur_border`` — rounded, sharp map inset over a blurred, slightly
  darkened copy of itself filling the frame (the "modern preview" look)
* ``spotlight`` — same layout, but the border copy is desaturated
  (color stays only inside)
* ``vignette`` — radial darkening towards the edges
* ``blurred_edges`` — vignette-style falloff with BLUR instead of
  darkness: sharp inside, increasingly blurred towards the edges
* ``rounded`` — rounded corners over a light backdrop (visible on the
  flat JPEG)

OpenTopoMap tiles are keyless; the license attribution is baked into
the bottom-right corner of every card.
"""

from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from django.conf import settings

OTM_TILE_URL = "https://tile.opentopomap.org/{z}/{x}/{y}.png"
TILE_SIZE = 256
USER_AGENT = "WodoreOG/1.0 (link previews; https://wodore.com)"
ATTRIBUTION = "© OpenTopoMap (CC-BY-SA) · © SRTM · © OpenStreetMap contributors"

CARD_WIDTH = 1200
CARD_HEIGHT = 630
CARD_ASPECT = CARD_WIDTH / CARD_HEIGHT
CARD_ZOOM = 16
EFFECTS = ("none", "blur_border", "spotlight", "vignette", "blurred_edges", "rounded")

# Marker/watermark geometry (owner-approved): symbol right of center,
# watermark on the left at the bottom.
MARKER_SIZE_PX = 170
MARKER_X = 0.60
WATERMARK_SIZE_PX = 270
WATERMARK_X = 0.18
WATERMARK_BOTTOM_PX = 10

_FONT_PATH = (
    Path(settings.BASE_DIR) / "docker/imagor/fonts/BarlowSemiCondensed-SemiBold.ttf"
)


def _deg_to_tile(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _fetch_tile(zoom: int, x: int, y: int) -> Image.Image:
    """Fetch one raster tile (monkeypatched in tests to avoid network)."""
    request = Request(
        OTM_TILE_URL.format(z=zoom, x=x, y=y), headers={"User-Agent": USER_AGENT}
    )
    with urlopen(request, timeout=10) as response:
        return Image.open(response).convert("RGB")


def _fetch_url(url: str) -> Image.Image | None:
    """Fetch an image URL (marker raster / watermark); None on failure."""
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=10) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGBA")
    except Exception:
        return None


def fetch_watermark() -> Image.Image | None:
    """The Wodore watermark PNG from the frontend host."""
    return _fetch_url(
        f"{settings.FRONTEND_DOMAIN.rstrip('/')}/meta/wodore_watermark.png"
    )


def fetch_marker(symbol_url: str, size_px: int) -> Image.Image | None:
    """Rasterize a symbol SVG via imagor (signing handled by the transformer)."""
    from server.apps.images.transfomer import ImagorImage

    url = ImagorImage(symbol_url).transform(size=f"{size_px}x{size_px}").get_full_url()
    return _fetch_url(url)


def _rounded(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *image.size], radius=radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def _apply_effect(card: Image.Image, effect: str, scale: float = 1.0) -> Image.Image:
    if effect == "none":
        return card
    if effect == "vignette":
        mask = Image.new("L", card.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [
                int(card.width * 0.15),
                int(card.height * 0.15),
                int(card.width * 0.85),
                int(card.height * 0.85),
            ],
            radius=int(200 * scale),
            fill=255,
        )
        mask = mask.filter(ImageFilter.GaussianBlur(int(120 * scale)))
        dark = Image.new("RGBA", card.size, (0, 0, 0, 110))
        out = card.convert("RGBA")
        out.paste(dark, (0, 0), Image.eval(mask, lambda v: 255 - v))
        return out.convert("RGB")

    if effect == "blurred_edges":
        blurred = card.filter(ImageFilter.GaussianBlur(int(10 * scale)))
        mask = Image.new("L", card.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [
                int(card.width * 0.14),
                int(card.height * 0.14),
                int(card.width * 0.86),
                int(card.height * 0.86),
            ],
            radius=int(200 * scale),
            fill=255,
        )
        mask = mask.filter(ImageFilter.GaussianBlur(int(90 * scale)))
        card.paste(blurred, (0, 0), Image.eval(mask, lambda v: 255 - v))
        return card

    # blur_border / spotlight: blurred (and optionally desaturated) copy
    # of the map fills the frame, the sharp rounded map sits on top.
    margin = int(26 * scale)
    radius = int(44 * scale)
    background = card.resize(
        (int(card.width * 1.15), int(card.height * 1.15)), Image.LANCZOS
    ).crop(
        (
            int(card.width * 0.075),
            int(card.height * 0.075),
            int(card.width * 0.075) + card.width,
            int(card.height * 0.075) + card.height,
        )
    )
    if effect == "spotlight":
        background = background.convert("L").convert("RGB")
    background = background.filter(ImageFilter.GaussianBlur(14))
    background = Image.eval(background, lambda v: int(v * 0.8))

    inner_w = card.width - margin * 2
    inner_h = card.height - margin * 2
    foreground = _rounded(card.resize((inner_w, inner_h), Image.LANCZOS), radius)
    background.paste(foreground, (margin, margin), foreground)
    return background


def render_static_map(
    lat: float,
    lon: float,
    zoom: int = CARD_ZOOM,
    width: int = CARD_WIDTH,
    height: int = CARD_HEIGHT,
    effect: str = "none",
    marker: Image.Image | None = None,
    marker_scale: float = 1.0,
    watermark: Image.Image | None = None,
    attribution: bool = True,
) -> bytes:
    """Render a complete og card of width x height, centered on (lat, lon).

    Marker, watermark, effects and attribution scale with the size
    (relative to the 1200x630 reference card).
    """
    scale = width / CARD_WIDTH
    xt, yt = _deg_to_tile(lat, lon, zoom)
    nx = math.ceil((width * 1.3) / TILE_SIZE) + 1
    ny = math.ceil((height * 1.3) / TILE_SIZE) + 1
    x0 = math.floor(xt) - nx // 2
    y0 = math.floor(yt) - ny // 2

    canvas = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
    for dx in range(nx):
        for dy in range(ny):
            canvas.paste(
                _fetch_tile(zoom, x0 + dx, y0 + dy), (dx * TILE_SIZE, dy * TILE_SIZE)
            )

    px = (xt - x0) * TILE_SIZE
    py = (yt - y0) * TILE_SIZE
    crop_w = width * 2
    crop_h = height * 2
    left = max(0, min(canvas.width * 2 - crop_w, int(px * 2 - crop_w / 2)))
    top = max(0, min(canvas.height * 2 - crop_h, int(py * 2 - crop_h / 2)))
    card = (
        canvas.resize((canvas.width * 2, canvas.height * 2), Image.LANCZOS)
        .crop((left, top, left + crop_w, top + crop_h))
        .resize((width, height), Image.LANCZOS)
    )

    if effect == "rounded":
        backdrop = Image.new("RGB", (width, height), (238, 242, 239))
        inner = _rounded(card, int(48 * scale))
        backdrop.paste(inner, (0, 0), inner)
        card = backdrop
    elif effect != "none":
        card = _apply_effect(card, effect, scale)

    if marker is not None:
        size = int(MARKER_SIZE_PX * scale * max(marker_scale, 0.1))
        marker_img = marker.copy()
        marker_img.thumbnail((size, size), Image.LANCZOS)
        card = card.convert("RGBA")
        card.alpha_composite(
            marker_img,
            (
                int(width * MARKER_X - marker_img.width / 2),
                int(height / 2 - marker_img.height / 2),
            ),
        )

    if watermark is not None:
        watermark_img = watermark.copy()
        watermark_img.thumbnail(
            (WATERMARK_SIZE_PX * 2, WATERMARK_SIZE_PX * 2), Image.LANCZOS
        )
        card = card.convert("RGBA")
        card.alpha_composite(
            watermark_img,
            (
                int(width * WATERMARK_X - watermark_img.width / 2),
                height - watermark_img.height - WATERMARK_BOTTOM_PX,
            ),
        )

    card = card.convert("RGB")
    if attribution:
        draw = ImageDraw.Draw(card, "RGBA")
        font_size = max(10, int(13 * scale))
        try:
            font = ImageFont.truetype(str(_FONT_PATH), font_size)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), ATTRIBUTION, font=font)
        tw = bbox[2] - bbox[0]
        pad = max(4, int(6 * scale))
        draw.rectangle(
            [width - tw - pad * 3, height - int(20 * scale), width, height],
            fill=(255, 255, 255, 120),
        )
        draw.text(
            (width - tw - pad * 2, height - int(19 * scale)),
            ATTRIBUTION,
            font=font,
            fill=(110, 110, 110, 170),
        )

    buffer = io.BytesIO()
    # JPEG: flat (no transparency) photographic-like content, ~5x smaller
    # than PNG at link-preview quality.
    card.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def static_map_cache_key(params: dict) -> str:
    """Stable storage key for a parameter set (any change re-renders)."""
    canonical = "&".join(
        f"{k}={params[k]}" for k in sorted(params) if params[k] is not None
    )
    digest = hashlib.sha1(canonical.encode()).hexdigest()[:20]
    return f"ogmaps/static-{digest}.png"
