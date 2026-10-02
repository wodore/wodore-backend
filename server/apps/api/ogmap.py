"""Static-map rendering for og:image fallback cards (OpenTopoMap).

Keyless raster tiles from OpenTopoMap, stitched around a coordinate with
Pillow. Rendered once per hut and stored via the default storage (the
URL stays stable; consumers bust caches with a ``?v=<modified>`` query
— see the hut meta endpoint). The type symbol and the Wodore watermark
are NOT baked here: the imagor pipeline composites them, this module
only produces the map canvas.

Attribution is baked into the bottom-right corner (OpenTopoMap/OSM
license requirement).
"""

from __future__ import annotations

import math
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

from django.conf import settings

OTM_TILE_URL = "https://tile.opentopomap.org/{z}/{x}/{y}.png"
TILE_SIZE = 256
USER_AGENT = "WodoreOG/1.0 (hut link previews; https://wodore.com)"
ATTRIBUTION = "© OpenTopoMap (CC-BY-SA) · © SRTM · © OpenStreetMap contributors"

# Card geometry (og:image standard aspect ratio).
CARD_WIDTH = 1200
CARD_HEIGHT = 630
CARD_ZOOM = 16

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


def render_static_map(
    lat: float, lon: float, zoom: int = CARD_ZOOM, attribution: bool = True
) -> bytes:
    """Render an OpenTopoMap card centered exactly on (lat, lon)."""
    xt, yt = _deg_to_tile(lat, lon, zoom)
    # Enough tiles to cover the card plus slack for the center crop.
    nx = math.ceil((CARD_WIDTH * 1.3) / TILE_SIZE) + 1
    ny = math.ceil((CARD_HEIGHT * 1.3) / TILE_SIZE) + 1
    x0 = math.floor(xt) - nx // 2
    y0 = math.floor(yt) - ny // 2

    canvas = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
    for dx in range(nx):
        for dy in range(ny):
            canvas.paste(
                _fetch_tile(zoom, x0 + dx, y0 + dy), (dx * TILE_SIZE, dy * TILE_SIZE)
            )

    # Center-crop on the coordinate at the card aspect ratio, 2x upscale
    # for crispness, then downscale with LANCZOS.
    px = (xt - x0) * TILE_SIZE
    py = (yt - y0) * TILE_SIZE
    crop_w = CARD_WIDTH * 2
    crop_h = CARD_HEIGHT * 2
    left = max(0, min(canvas.width - crop_w, int(px * 2 - crop_w / 2)))
    top = max(0, min(canvas.height - crop_h, int(py * 2 - crop_h / 2)))
    card = (
        canvas.resize((canvas.width * 2, canvas.height * 2), Image.LANCZOS)
        .crop((left, top, left + crop_w, top + crop_h))
        .resize((CARD_WIDTH, CARD_HEIGHT), Image.LANCZOS)
    )

    if attribution:
        draw = ImageDraw.Draw(card, "RGBA")
        try:
            font = ImageFont.truetype(str(_FONT_PATH), 18)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), ATTRIBUTION, font=font)
        tw = bbox[2] - bbox[0]
        pad = 6
        draw.rectangle(
            [CARD_WIDTH - tw - pad * 3, CARD_HEIGHT - 26, CARD_WIDTH, CARD_HEIGHT],
            fill=(255, 255, 255, 170),
        )
        draw.text(
            (CARD_WIDTH - tw - pad * 2, CARD_HEIGHT - 24),
            ATTRIBUTION,
            font=font,
            fill=(60, 60, 60, 220),
        )

    import io

    buffer = io.BytesIO()
    card.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
