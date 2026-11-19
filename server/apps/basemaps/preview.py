"""Live style preview endpoint + linting for the MapLayer admin.

The change form posts the CURRENT editor content (not the saved row)
here; this endpoint runs the same serve-time pipeline the style
endpoint uses (env token resolution, parameter token resolution, URL
absolutization) plus the basemap composition for overlays, then
returns:

* the renderable MapLibre style document
* styl findings (E/W codes with line positions when the binary is on PATH)
* subset walker findings (for subset-profile rows or any document)
* the resolved basemap's slug (when an overlay asked for one)

The admin widget debounces editor changes and re-posts here; the
MapLibre canvas does a diff-based setStyle() with the returned
document; the lint findings highlight gutter lines in the editor.
"""

import json
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.resolution import (
    absolutize_urls,
    resolve_setting,
    resolve_tokens,
    substitute_env_tree,
)
from server.apps.basemaps.seed_lib import compose_basemap_style
from server.apps.basemaps.validation import validate_subset_style

#: styl binary lookup (None = not on PATH; the endpoint reports a hint)
_STYL: str | None = shutil.which("styl")


def _styl_findings(style_json: str) -> list[dict[str, Any]]:
    """Run the styl linter on a raw style document; return findings."""
    if _STYL is None:
        return []
    try:
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(style_json)
            path = f.name
        result = subprocess.run(
            [_STYL, "lint", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        Path(path).unlink(missing_ok=True)
    except (OSError, subprocess.TimeoutExpired):
        return []
    findings: list[dict[str, Any]] = []
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        # styl output format: path:line:col: [Exxx] message
        # or: path: [Exxx] message
        parts = line.split(":", 3)
        if len(parts) >= 3 and parts[1].strip().isdigit():
            findings.append(
                {
                    "source": "styl",
                    "severity": "error" if "[E" in line else "warning",
                    "line": int(parts[1].strip()),
                    "message": parts[-1].strip() if len(parts) > 3 else line,
                }
            )
        elif "[E" in line or "[W" in line:
            findings.append(
                {
                    "source": "styl",
                    "severity": "error" if "[E" in line else "warning",
                    "line": None,
                    "message": line,
                }
            )
    return findings


def _walker_findings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the subset walker; return findings (always — any doc)."""
    try:
        validate_subset_style(doc)
        return []
    except Exception as exc:  # noqa: BLE004
        messages = str(exc).split("; ")
        return [
            {
                "source": "subset",
                "severity": "error",
                "line": None,
                "message": msg.strip(),
            }
            for msg in messages
            if msg.strip()
        ]


@csrf_exempt
@require_POST
def preview_live(request: HttpRequest) -> HttpResponse:
    """POST body: {style_json: str, basemap_slug: str|null, profile: str}."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    raw_style = body.get("style_json", "")
    basemap_slug = body.get("basemap_slug") or None
    profile = body.get("profile", "")

    # Parse the editor content
    try:
        doc = json.loads(raw_style)
    except json.JSONDecodeError as exc:
        return JsonResponse(
            {
                "error": f"JSON parse error: {exc}",
                "lint": [
                    {
                        "source": "json",
                        "severity": "error",
                        "line": exc.lineno,
                        "message": exc.msg,
                    }
                ],
            }
        )

    # Lint (always: walker on any doc; styl when available)
    lint = _styl_findings(raw_style)
    if profile != "subset":
        # full-profile rows: walker findings are informational, not
        # blocking — the doc is ALLOWED to leave the subset whitelist
        walker = _walker_findings(doc)
        for w in walker:
            w["severity"] = "info"
        lint += walker
    else:
        lint += _walker_findings(doc)

    # Resolve the document (serve-time pipeline, minus volatile params)
    resolved = substitute_env_tree(doc)
    resolved = resolve_tokens(resolved, {})
    tile_url = resolve_setting("MARTIN_TILE_URL")
    resolved = absolutize_urls(resolved, tile_url, api_url="")

    # For overlays: compose on the requested basemap
    basemap_used = None
    if basemap_slug:
        basemap = MapLayer.objects.filter(
            slug=basemap_slug, role=MapLayer.Role.basemap, is_active=True
        ).first()
        if basemap is not None and basemap.style is not None:
            basemap_doc = basemap.style
            # resolve basemap tokens too
            basemap_doc = substitute_env_tree(basemap_doc)
            basemap_doc = resolve_tokens(basemap_doc, {})
            basemap_doc = absolutize_urls(basemap_doc, tile_url, api_url="")

            # compose basemap blocks (the reverse: our overlay's block
            # would be in the basemap — but we're previewing the
            # overlay, so we want the basemap's blocks MINUS ours)
            blocks, _inputs = _basemap_blocks_excluding(basemap, body.get("slug", ""))
            if blocks:
                basemap_doc = compose_basemap_style(
                    dict(basemap_doc), blocks, anchors=basemap.anchors
                )

            # append the overlay's sources/sprite/layers on top
            for key, source in (resolved.get("sources") or {}).items():
                basemap_doc.setdefault("sources", {})[key] = source
            for sprite in resolved.get("sprite") or []:
                if isinstance(sprite, dict):
                    sprite_id = sprite.get("id")
                    existing = {
                        s.get("id")
                        for s in (basemap_doc.get("sprite") or [])
                        if isinstance(s, dict)
                    }
                    if sprite_id not in existing:
                        basemap_doc.setdefault("sprite", []).append(sprite)
                elif isinstance(sprite, str) and sprite not in (
                    basemap_doc.get("sprite") or []
                ):
                    basemap_doc.setdefault("sprite", []).append(sprite)
            for layer in resolved.get("layers") or []:
                basemap_doc.setdefault("layers", []).append(layer)
            if resolved.get("glyphs"):
                basemap_doc.setdefault("glyphs", resolved["glyphs"])

            resolved = basemap_doc
            basemap_used = basemap.slug

    return JsonResponse(
        {
            "style": resolved,
            "lint": lint,
            "basemap": basemap_used,
            "styl_available": _STYL is not None,
        }
    )


def _basemap_blocks_excluding(
    basemap: MapLayer, exclude_slug: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect basemap blocks from overlay rows, excluding one slug."""

    if (
        basemap.role != MapLayer.Role.basemap
        or basemap.profile == MapLayer.Profile.subset
    ):
        return [], []
    overlays = (
        MapLayer.objects.filter(role=MapLayer.Role.overlay, is_active=True)
        .only("pk", "slug", "spec", "profile", "modified", "config", "role")
        .order_by("pk")
    )
    blocks: list[dict[str, Any]] = []
    inputs: list[str] = []
    seen: set[str] = set()
    for overlay in overlays:
        if overlay.slug == exclude_slug or overlay.slug in seen:
            continue
        block = (overlay.config or {}).get("basemap")
        if isinstance(block, dict) and block.get("layers"):
            blocks.append(block)
            inputs.append(f"basemap-block:{overlay.pk}:{overlay.modified.isoformat()}")
            seen.add(overlay.slug)
    return blocks, inputs
