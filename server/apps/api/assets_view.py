"""Backend-served static brand assets.

Serves the small, immutable brand files the og/imagor pipeline
references — e.g. the Wodore watermark composited onto og photos.
No backend→frontend asset dependencies: the files live in
``server/apps/api/assets/`` and are served from the API host
(``/assets/logo/wodore_watermark.png``).

Requests may append ``?v=<hash>`` for imagor/CDN cache busting — the
query is not validated, it only varies the URL; the digest of the
bundled file is exposed as :func:`logo_version` for exactly that.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest, HttpResponse

#: Directory with the bundled assets (shipped with the image).
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

#: Servable assets — explicit whitelist, no directory traversal.
ASSET_FILES = frozenset({"wodore_watermark.png"})

#: Long cache: the content-addressed ``?v=`` query varies the URL on
#: asset changes, so cached copies can safely outlive a deploy.
CACHE_CONTROL = "public, max-age=604800"


def serve_logo(request: HttpRequest, name: str) -> HttpResponse:
    """Serve one whitelisted asset file from ``assets/``."""
    if name not in ASSET_FILES:
        raise Http404(f"Unknown asset {name!r}.")
    file_path = ASSETS_DIR / name
    if not file_path.is_file():
        raise Http404(f"Asset {name!r} is not bundled.")
    response = FileResponse(
        file_path.open("rb"), content_type="image/png", filename=name
    )
    response.headers["Cache-Control"] = CACHE_CONTROL
    return response


def logo_version(name: str = "wodore_watermark.png") -> str:
    """Short content digest of an asset — append as ``?v=`` so imagor
    results and CDN entries bust when the file is replaced."""
    try:
        return hashlib.sha1((ASSETS_DIR / name).read_bytes()).hexdigest()[:8]
    except OSError:
        return "0"
