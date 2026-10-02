"""Static-map card rendering for og:image fallbacks (OpenTopoMap).

Renders the map card in Pillow: canvas, optional marker (the entity's
type symbol raster) and optional visual effects — callers get a final
1200x630 JPEG. The Wodore logo is NOT baked in: og consumers composite
it via imagor on top of this endpoint's output.

Effects (``effect=`` parameter):

* ``none`` — plain map
* ``blur_border`` — rounded, sharp map inset over a blurred, slightly
  darkened copy of itself filling the frame (the "modern preview" look)
* ``spotlight`` — same layout, but the border copy is desaturated
  (color stays only inside)
* ``vignette`` — radial darkening towards the edges
* ``blurred_edges`` — vignette-style falloff with BLUR instead of
  darkness: sharp inside, increasingly blurred towards the edges

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
EFFECTS = ("none", "blur_border", "spotlight", "vignette", "blurred_edges")

# Marker geometry (owner-approved): symbol right of center.
MARKER_SIZE_PX = 170
MARKER_X = 0.60

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


TILE_WORKERS = 4
TILE_ATTEMPTS = 3


def _fetch_tile_retry(zoom: int, x: int, y: int) -> Image.Image:
    """One tile with 429 backoff (OpenTopoMap throttles bursts — honor
    Retry-After when present, exponential otherwise)."""
    import time
    import urllib.error

    for attempt in range(TILE_ATTEMPTS):
        try:
            return _fetch_tile(zoom, x, y)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < TILE_ATTEMPTS - 1:
                wait = error.headers.get("Retry-After") if error.headers else None
                time.sleep(float(wait) if wait else 0.5 * (2**attempt))
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


def _fetch_tiles(zoom: int, coords: list[tuple[int, int]]) -> list[Image.Image]:
    """Fetch tiles in parallel (bounded — OTM is community-hosted; a
    modest worker pool keeps bursts polite while cutting wall time)."""
    from concurrent.futures import ThreadPoolExecutor

    if len(coords) == 1:
        return [_fetch_tile_retry(zoom, *coords[0])]
    with ThreadPoolExecutor(max_workers=min(TILE_WORKERS, len(coords))) as pool:
        return list(pool.map(lambda c: _fetch_tile_retry(zoom, *c), coords))


def _fetch_url(url: str) -> Image.Image | None:
    """Fetch an image URL (marker raster); None on failure."""
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=10) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGBA")
    except Exception:
        return None


def fetch_marker(symbol_url: str, size_px: int) -> Image.Image | None:
    """Fetch the symbol as a sharp, transparent raster via imagor.

    Empirically (imagor v1.9.6 + libvips):
    * a plain WxH transform flattens SVG transparency to opaque black,
    * fit-in alone returns the SVG at its intrinsic 48px,
    * ``dpi(n)`` is the only lever that scales the SVG rasterization —
      dpi(1440) renders the 48px symbols at 960px with alpha preserved
      (fit-in + format(png) required alongside).
    Callers downscale from the high-res raster with LANCZOS — the
    marker stays sharp at any size, as a vector should.
    """
    from server.apps.images.transfomer import ImagorImage

    url = (
        ImagorImage(symbol_url)
        .transform(
            size=f"{size_px * 2}x{size_px * 2}",
            fit=True,
            filters=["dpi(1440)", "format(png)"],
        )
        .get_full_url()
    )
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
    attribution: bool = True,
    offset_x: int = 0,
    offset_y: int = 0,
) -> bytes:
    """Render a complete og card of width x height, centered on (lat, lon).

    Marker, effects and attribution scale with the size (relative to
    the 1200x630 reference card). The Wodore logo is NOT baked in —
    og consumers composite it via imagor.
    """
    scale = width / CARD_WIDTH
    xt, yt = _deg_to_tile(lat, lon, zoom)
    # Just enough tiles to cover the card wherever the coordinate lands
    # within the center tile (the old 1.3x slack fetched 40 tiles).
    nx = math.ceil(width / TILE_SIZE) + 2
    ny = math.ceil(height / TILE_SIZE) + 2
    x0 = math.floor(xt) - nx // 2
    y0 = math.floor(yt) - ny // 2

    coords = [(x0 + dx, y0 + dy) for dx in range(nx) for dy in range(ny)]
    tiles = _fetch_tiles(zoom, coords)
    canvas = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
    for (dx, dy), tile in zip(
        ((dx, dy) for dx in range(nx) for dy in range(ny)), tiles
    ):
        canvas.paste(tile, (dx * TILE_SIZE, dy * TILE_SIZE))

    # Crop at NATIVE tile resolution (256px tiles at zoom 16 are ~1:1
    # with the card at 1200px wide) — the old upscale-then-downscale
    # detour doubled CPU time for no sharpness gain.
    px = (xt - x0) * TILE_SIZE
    py = (yt - y0) * TILE_SIZE
    left = max(0, min(canvas.width - width, int(px - width / 2) + offset_x))
    top = max(0, min(canvas.height - height, int(py - height / 2) + offset_y))
    card = canvas.crop((left, top, left + width, top + height))
    if card.size != (width, height):
        card = card.resize((width, height), Image.LANCZOS)

    if effect != "none":
        card = _apply_effect(card, effect, scale)

    if marker is not None:
        size = int(MARKER_SIZE_PX * scale * max(marker_scale, 0.1))
        marker_img = marker.copy()
        # LANCZOS downscale from the high-dpi raster (fetch_marker): the
        # vector stays sharp at any target size.
        marker_img = marker_img.resize((size, size), Image.LANCZOS)
        card = card.convert("RGBA")
        card.alpha_composite(
            marker_img,
            (
                int(width * MARKER_X - marker_img.width / 2),
                int(height / 2 - marker_img.height / 2),
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
