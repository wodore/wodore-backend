"""Live style preview endpoint + linting for the MapLayer admin.

The change form posts the CURRENT editor content (not the saved row)
here; this endpoint runs the same serve-time pipeline the style
endpoint uses (env token resolution, parameter token resolution, URL
absolutization) plus the basemap composition for overlays, then
returns:

* the renderable MapLibre style document
* styl findings (via the existing ``validation.run_styl`` helper)
* subset walker findings (for subset-profile rows or any document)
* the resolved basemap's slug (when an overlay asked for one)

The admin widget debounces editor changes and re-posts here; the
MapLibre canvas does a diff-based setStyle() with the returned
document; the lint findings highlight gutter lines in the editor.
"""

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from server.apps.basemaps.api import basemap_composition
from server.apps.basemaps.models import MapLayer
from server.apps.basemaps.resolution import (
    absolutize_urls,
    resolve_setting,
    resolve_tokens,
    substitute_env_tree,
)
from server.apps.basemaps.seed_lib import compose_basemap_style
from server.apps.basemaps.validation import run_styl, validate_subset_style


def _normalize_sprite(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize the sprite field to array-of-dicts (spec allows str)."""
    sprite = doc.get("sprite")
    if isinstance(sprite, str):
        doc["sprite"] = [{"id": "default", "url": sprite}]
    elif sprite is None:
        empty_sprite: list[dict[str, str]] = []
        doc["sprite"] = empty_sprite
    return doc


def _styl_findings(
    doc: dict[str, Any], ignored_rules: list[str] | None
) -> list[dict[str, Any]]:
    """Run the styl linter via the existing helper; return findings."""
    ignored: list[str] = ignored_rules or []
    if ignored == ["*"]:
        return []  # wholesale skip (external-derived styles)
    result = run_styl(doc, ignored)
    if result is None:
        return []
    findings: list[dict[str, Any]] = []
    for msg in result.errors:
        findings.append(
            {
                "source": "styl",
                "severity": "error",
                "line": None,
                "message": msg,
            }
        )
    for msg in result.warnings:
        findings.append(
            {
                "source": "styl",
                "severity": "warning",
                "line": None,
                "message": msg,
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


def _resolve_document(
    doc: dict[str, Any],
    layer: MapLayer | None,
    tile_url: str,
) -> dict[str, Any]:
    """Resolve a document through the serve-time pipeline."""
    resolved = substitute_env_tree(doc)
    # Parameter tokens: the row's authored defaults, or empty for a
    # document that has no row yet (live editing before save)
    if layer is not None and layer.pk:
        values = layer.authored_parameter_values()
        for link in layer.layer_parameters.select_related("parameter"):
            if values.get(link.parameter.slug) is None:
                served = link.parameter.serve_time_value()
                if served is not None:
                    values[link.parameter.slug] = served
    else:
        values: dict[str, Any] = {}
    resolved = resolve_tokens(resolved, values)
    api_url = ""
    resolved = absolutize_urls(resolved, tile_url, api_url=api_url)
    return _normalize_sprite(resolved)


def _compose_overlay_on_basemap(
    overlay_doc: dict[str, Any],
    overlay_layer: MapLayer,
    basemap_slug: str,
    tile_url: str,
) -> tuple[dict[str, Any], str | None]:
    """Compose an overlay on a basemap for preview (frontend parity)."""
    basemap = MapLayer.pick_variant(
        MapLayer.objects.filter(
            slug=basemap_slug, role=MapLayer.Role.basemap, is_active=True
        ),
        spec=None,
        profile=MapLayer.Profile.full,
    )
    if basemap is None or basemap.style is None:
        return overlay_doc, None

    # S1 fix: compose blocks FIRST (on the raw basemap document),
    # THEN resolve — the blocks carry {{env:…}} tokens that the
    # serve-time pipeline must resolve too (the old order left them
    # as literal tokens MapLibre can't fetch)
    basemap_doc = dict(basemap.style)

    all_blocks, _inputs = basemap_composition(basemap)
    if all_blocks:
        basemap_doc = compose_basemap_style(
            basemap_doc, all_blocks, anchors=basemap.anchors
        )
    overlay_prefix = _overlay_block_prefix(overlay_layer)
    if overlay_prefix:
        basemap_doc["layers"] = [
            layer
            for layer in basemap_doc.get("layers", [])
            if not str(layer.get("id", "")).startswith(overlay_prefix)
        ]

    # NOW resolve the composed basemap (env + parameter tokens + URL
    # absolutization — everything, including the block URLs)
    basemap_doc = _resolve_document(basemap_doc, basemap, tile_url)

    # Append the overlay's sources/sprite/layers on top
    for key, source in (overlay_doc.get("sources") or {}).items():
        basemap_doc.setdefault("sources", {}).setdefault(key, source)
    overlay_sprite = overlay_doc.get("sprite") or []
    if isinstance(overlay_sprite, str):
        overlay_sprite = [{"id": "default", "url": overlay_sprite}]
    existing_ids = {
        s.get("id") for s in (basemap_doc.get("sprite") or []) if isinstance(s, dict)
    }
    for sprite in overlay_sprite:
        if isinstance(sprite, dict) and sprite.get("id") not in existing_ids:
            basemap_doc.setdefault("sprite", []).append(sprite)
    # Overlay layers append at the END (above everything — the frontend
    # appends overlay layers via addLayer which places them on top)
    for layer in overlay_doc.get("layers") or []:
        basemap_doc.setdefault("layers", []).append(layer)
    if overlay_doc.get("glyphs"):
        basemap_doc.setdefault("glyphs", overlay_doc["glyphs"])

    return basemap_doc, basemap.slug


def _overlay_block_prefix(layer: MapLayer) -> str:
    """The wd-basemap-<slug>-* prefix from the overlay's config.basemap."""
    block = (layer.config or {}).get("basemap")
    if isinstance(block, dict):
        return str(block.get("id_prefix", ""))
    return ""


@csrf_exempt
@require_POST
def preview_live(request: HttpRequest) -> HttpResponse:
    """POST body: {style_json: str, basemap_slug: str|null, profile: str, slug: str, object_id: int}.

    ``@csrf_exempt`` is safe here: the endpoint is read-only (returns
    JSON, never mutates), requires an authenticated admin session AND
    the ``basemaps.change_maplayer`` model permission, and is only
    called same-origin from the admin page. The standard CSRF token
    flow cannot work: ``CSRF_COOKIE_HTTPONLY=True`` prevents JS from
    reading the cookie, and the form's ``csrfmiddlewaretoken`` is a
    masked token for form POST fields, not the ``X-CSRFToken`` header
    (they are DIFFERENT values — Django compares the header against
    the cookie, not the form token).
    """
    # Permission: CHANGE permission on this model — not just staff.
    # The endpoint resolves env tokens (including API keys) and must
    # not leak them to read-only staff (Opus review B2). NOTE: the
    # isinstance check against django.contrib.auth.models.User was
    # WRONG — this project uses a CUSTOM user model (accounts.User);
    # has_perm works on both, no isinstance needed.
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    # has_perm on the runtime user (custom model) — getattr bridges the
    # type gap: the stubs type request.user as AbstractBaseUser which
    # does not declare has_perm (only the concrete User classes do)
    def _has_change_perm(perm: str) -> bool:
        checker = getattr(request.user, "has_perm", None)
        if checker is None:
            return False
        return bool(checker(perm))

    if not _has_change_perm("basemaps.change_maplayer"):
        return JsonResponse(
            {"error": "You need change permission on map layers"}, status=403
        )

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "invalid JSON body"}, status=400)

    raw_style = body.get("style_json", "")
    basemap_slug = body.get("basemap_slug") or None
    profile = body.get("profile", "")
    slug = body.get("slug", "")
    object_id = body.get("object_id")

    # Find the row (may be None for unsaved — live editing)
    layer: MapLayer | None = None
    if object_id:
        layer = MapLayer.objects.filter(pk=object_id).first()
    elif slug:
        layer = MapLayer.objects.filter(slug=slug).first()

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

    if not isinstance(doc, dict):
        return JsonResponse(
            {
                "error": "style must be a JSON object",
                "lint": [
                    {
                        "source": "json",
                        "severity": "error",
                        "line": None,
                        "message": "top-level document must be an object",
                    }
                ],
            }
        )

    # Lint
    styl_ignored = (layer.styl_ignored_rules if layer else None) or []
    lint = _styl_findings(doc, styl_ignored)
    if profile != "subset":
        walker = _walker_findings(doc)
        for w in walker:
            w["severity"] = "info"
        lint += walker
    else:
        lint += _walker_findings(doc)

    tile_url = resolve_setting("MARTIN_TILE_URL")
    resolved = _resolve_document(doc, layer, tile_url)

    # For overlays: compose on the requested basemap
    basemap_used = None
    if basemap_slug and layer is not None:
        resolved, basemap_used = _compose_overlay_on_basemap(
            resolved, layer, basemap_slug, tile_url
        )

    return JsonResponse(
        {
            "style": resolved,
            "lint": lint,
            "basemap": basemap_used,
        }
    )
