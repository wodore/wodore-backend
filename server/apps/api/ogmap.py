"""Static-map card rendering for og:image fallbacks (OpenTopoMap).

Renders the map card in Pillow: canvas, optional marker (the entity's
type symbol raster) and optional visual effects — callers get a final
1200x630 JPEG. The Wodore logo is NOT baked in: og consumers composite
it via imagor on top of this endpoint's output.

Effects (``effect=`` parameter):

* ``none`` — plain map
* ``blur_border`` — rounded, sharp map inset over a blurred, slightly
  darkened copy of itself filling the frame (the "modern preview" look)
* ``spotlight`` — smooth falloff, no inset: the sharp, colorful center
  fades into a darker, desaturated, gently blurred outside (color
  stays only under the spotlight)
* ``vignette`` — radial darkening towards the edges
* ``blurred_edges`` — vignette-style falloff with BLUR instead of
  darkness: sharp inside, increasingly blurred towards the edges

OpenTopoMap tiles are keyless; the license attribution is baked into
the bottom-right corner of every card.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

if TYPE_CHECKING:
    import requests

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

#: Bump when the rendering itself changes (effects, marker/watermark
#: geometry, output encoding). Folded into the render cache key and —
#: via the fallback feature URLs — into the ``v=`` busting parameter, so
#: a renderer change re-renders every card AND regenerates the imagor
#: composites built on top of them.
RENDER_VERSION = 6

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
    """Fetch one raster tile (monkeypatched in tests to avoid network).

    Uses a shared requests.Session: urllib openen made a fresh TLS
    handshake per tile (~85ms each); connection keep-alive cuts a tile
    fetch to ~25ms.
    """

    response = _session().get(OTM_TILE_URL.format(z=zoom, x=x, y=y), timeout=10)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


_SESSION_LOCK = threading.Lock()
_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    """Process-wide session (urllib3 pool is thread-safe; connections
    are reused across the parallel fetchers AND across renders)."""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            import requests

            _SESSION = requests.Session()
            _SESSION.headers["User-Agent"] = USER_AGENT
        return _SESSION


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

    if effect == "spotlight":
        # Smooth falloff — no inset, no frame: a warm, sharp, slightly
        # saturated island under a cold spotlight. The outside is
        # bokeh-blurred, tinted toward moonlight blue and dimmed to 0.5
        # — the temperature contrast (warm center / cold surround)
        # reads as depth without any frame edge.
        outside = card.convert("L")
        outside = outside.filter(ImageFilter.GaussianBlur(int(12 * scale)))
        outside = ImageOps.colorize(outside, black=(18, 26, 40), white=(198, 208, 224))
        outside = Image.eval(outside, lambda v: int(v * 0.5))
        mask = Image.new("L", card.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [
                int(card.width * 0.18),
                int(card.height * 0.18),
                int(card.width * 0.82),
                int(card.height * 0.82),
            ],
            radius=int(260 * scale),
            fill=255,
        )
        mask = mask.filter(ImageFilter.GaussianBlur(int(130 * scale)))
        # Warm island: stronger saturation boost plus a slight
        # brightness lift, so the center really pops against the cold
        # moonlight surround (owner review: "increase the warm natural
        # center").
        out = ImageEnhance.Color(card.convert("RGB")).enhance(1.15)
        out = ImageEnhance.Brightness(out).enhance(1.03)
        out.paste(outside, (0, 0), Image.eval(mask, lambda v: 255 - v))
        return out

    # blur_border: blurred copy of the map fills the frame, the sharp
    # rounded map sits on top.
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
    og consumers composite it via imagor (from the backend-served
    asset) on top of this output.
    """
    plan = _plan_tiles(
        lat, lon, zoom, width, height, offset_x, offset_y, marker is not None
    )
    tiles = _fetch_tiles(zoom, plan["coords"])
    return _composite_card(
        tiles, plan, marker, width, height, effect, marker_scale, attribution
    )


def _plan_tiles(
    lat: float,
    lon: float,
    zoom: int,
    width: int,
    height: int,
    offset_x: int,
    offset_y: int,
    has_marker: bool,
) -> dict:
    """EXACT tile range covering the crop window — no centering slack
    (the grid formula fetched ~35 tiles; ~15-20 are actually needed).
    The marker sits right of center (MARKER_X) — shift the map view
    with it so the symbol lands ON the entity's true position, not
    beside it (owner review: the 0.5→0.6 offset was hut-photo framing,
    for the symbol the map must move along)."""
    xt, yt = _deg_to_tile(lat, lon, zoom)
    # EXACT tile range covering the crop window — no centering slack
    # (the grid formula fetched ~35 tiles; ~15-20 are actually needed).
    # The marker sits right of center (MARKER_X) — shift the map view
    # with it so the symbol lands ON the entity's true position, not
    # beside it (owner review: the 0.5→0.6 offset was hut-photo framing,
    # for the symbol the map must move along).
    marker_shift = int(width * (MARKER_X - 0.5)) if has_marker else 0
    abs_left = xt * TILE_SIZE - width / 2 + offset_x - marker_shift
    abs_top = yt * TILE_SIZE - height / 2 + offset_y
    x0 = math.floor(abs_left / TILE_SIZE)
    x1 = math.floor((abs_left + width) / TILE_SIZE)
    y0 = math.floor(abs_top / TILE_SIZE)
    y1 = math.floor((abs_top + height) / TILE_SIZE)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1

    coords = [(x0 + dx, y0 + dy) for dx in range(nx) for dy in range(ny)]
    left = int(round(abs_left)) - x0 * TILE_SIZE
    top = int(round(abs_top)) - y0 * TILE_SIZE
    return {"coords": coords, "nx": nx, "ny": ny, "left": left, "top": top}


def _composite_card(
    tiles: list[Image.Image],
    plan: dict,
    marker: Image.Image | None,
    width: int,
    height: int,
    effect: str,
    marker_scale: float,
    attribution: bool,
) -> bytes:
    """Pure-CPU composite: canvas, crop, effects, marker, attribution, JPEG."""
    scale = width / CARD_WIDTH
    nx, ny = plan["nx"], plan["ny"]
    canvas = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))

    canvas = Image.new("RGB", (nx * TILE_SIZE, ny * TILE_SIZE))
    for (dx, dy), tile in zip(
        ((dx, dy) for dx in range(nx) for dy in range(ny)), tiles
    ):
        canvas.paste(tile, (dx * TILE_SIZE, dy * TILE_SIZE))

    # Crop at NATIVE tile resolution (256px tiles at zoom 16 are ~1:1
    # with the card at 1200px wide) — the old upscale-then-downscale
    # detour doubled CPU time for no sharpness gain.
    left, top = plan["left"], plan["top"]
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
    """Stable storage key for a parameter set (any change re-renders).

    The renderer version is folded in: a rendering change (effect,
    geometry) re-renders every card even with identical request
    parameters.
    """
    canonical = "&".join(
        f"{k}={params[k]}" for k in sorted(params) if params[k] is not None
    )
    canonical += f"&rv={RENDER_VERSION}"
    digest = hashlib.sha1(canonical.encode()).hexdigest()[:20]
    return f"ogmaps/static-{digest}.png"


# ---------------------------------------------------------------------------
# Async render path (async PoC, openspec: async-api-staging)
#
# The endpoint's I/O (N tiles + the marker raster) overlaps in ONE
# httpx.AsyncClient via asyncio.gather - the marker no longer serializes
# behind the tiles. TILE_WORKERS still bounds concurrent tile fetches
# (asyncio.Semaphore), so OpenTopoMap sees the same politeness as with
# the thread pool. The PIL composite is CPU work and runs in a bridged
# thread (sync_to_async) so the event loop keeps serving other requests.
# The sync path above (ThreadPool + requests.Session) stays for sync
# callers and tests.
# ---------------------------------------------------------------------------


async def _fetch_tile_async(
    client: httpx.AsyncClient, zoom: int, x: int, y: int
) -> bytes:
    """Fetch one tile as raw bytes (decoding happens in the bridged
    composite thread - the event loop only does I/O)."""
    response = await client.get(OTM_TILE_URL.format(z=zoom, x=x, y=y))
    response.raise_for_status()
    return response.content


async def _fetch_tile_retry_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    zoom: int,
    x: int,
    y: int,
) -> bytes:
    """One tile (raw bytes) with 429 backoff (async twin of
    _fetch_tile_retry)."""
    for attempt in range(TILE_ATTEMPTS):
        try:
            async with semaphore:
                return await _fetch_tile_async(client, zoom, x, y)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429 and attempt < TILE_ATTEMPTS - 1:
                wait = error.response.headers.get("Retry-After")
                await asyncio.sleep(float(wait) if wait else 0.5 * (2**attempt))
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


async def fetch_marker_async(
    client: httpx.AsyncClient, symbol_url: str, size_px: int
) -> bytes | None:
    """Async twin of fetch_marker (imagor rasterization of the symbol);
    raw PNG bytes, None on failure."""
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
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except Exception:
        return None


async def render_static_map_async(
    lat: float,
    lon: float,
    zoom: int = CARD_ZOOM,
    width: int = CARD_WIDTH,
    height: int = CARD_HEIGHT,
    effect: str = "none",
    marker_url: str | None = None,
    marker_size_px: int = 512,
    marker_scale: float = 1.0,
    attribution: bool = True,
    offset_x: int = 0,
    offset_y: int = 0,
) -> bytes:
    """Async render: tiles + marker overlap in one TaskGroup (a failing
    fetch cancels its siblings instead of leaking closed-client errors),
    decode + composite in a bridged thread."""
    from asgiref.sync import sync_to_async

    plan = _plan_tiles(
        lat, lon, zoom, width, height, offset_x, offset_y, bool(marker_url)
    )
    semaphore = asyncio.Semaphore(TILE_WORKERS)
    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        async with asyncio.TaskGroup() as tg:
            tile_tasks = [
                tg.create_task(_fetch_tile_retry_async(client, semaphore, zoom, x, y))
                for (x, y) in plan["coords"]
            ]
            marker_task = (
                tg.create_task(fetch_marker_async(client, marker_url, marker_size_px))
                if marker_url
                else None
            )

    tiles_bytes = [task.result() for task in tile_tasks]
    marker_bytes = marker_task.result() if marker_task is not None else None

    return await sync_to_async(_decode_and_composite)(
        tiles_bytes,
        marker_bytes,
        plan,
        width,
        height,
        effect,
        marker_scale,
        attribution,
    )


def _decode_and_composite(
    tiles_bytes: list[bytes],
    marker_bytes: bytes | None,
    plan: dict,
    width: int,
    height: int,
    effect: str,
    marker_scale: float,
    attribution: bool,
) -> bytes:
    """Decode fetched bytes and composite (runs in the bridged thread —
    PIL decode is CPU work and must not touch the event loop)."""
    tiles = [Image.open(io.BytesIO(b)).convert("RGB") for b in tiles_bytes]
    marker = (
        Image.open(io.BytesIO(marker_bytes)).convert("RGBA") if marker_bytes else None
    )
    return _composite_card(
        tiles, plan, marker, width, height, effect, marker_scale, attribution
    )
