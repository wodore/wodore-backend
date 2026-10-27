"""Structural validation for MapLibre styles and parameter tokens.

Thin pydantic structural checks only — deliberately NOT jsonschema
against the full MapLibre style spec (expressions are open-ended and
the spec is huge/brittle). What we enforce:

* ``version == 8``, ``sources`` object, ``layers`` list of
  ``{id, type, ...}`` — enough to catch corrupt pastes early.
* Parameter tokens are standalone string nodes ``"{{slug}}"`` with a
  conservative slug charset; unknown tokens are reported by the model's
  ``clean()``.
* ``opacity-curve`` widget defaults/overrides: ``interpolate`` over
  ``zoom`` with strictly ascending stops and opacity values in 0–1.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import pydantic

from server.apps.envvars.registry import resolve_setting

TOKEN_RE = re.compile(r"^\{\{([a-z0-9][a-z0-9_.\-]*)\}\}$")
ENV_TOKEN_RE = re.compile(r"\{\{env:([A-Z0-9_]+)\}\}")

#: Rules-version shape — dotted decimals (``26.4.4``, ``0.1``).
VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


class StyleValidationError(ValueError):
    """Raised when a style document fails structural validation."""


class _StyleLayer(pydantic.BaseModel):
    """Minimal layer shape — everything else passes through."""

    model_config = pydantic.ConfigDict(extra="allow")

    id: str
    type: str


class _StyleSpec(pydantic.BaseModel):
    """Minimal MapLibre StyleSpecification shape."""

    model_config = pydantic.ConfigDict(extra="allow")

    version: int
    sources: dict[str, dict[str, Any]]
    layers: list[_StyleLayer]

    @pydantic.field_validator("version")
    @classmethod
    def _version_8(cls, value: int) -> int:
        if value != 8:
            msg = f"style version must be 8, got {value}"
            raise ValueError(msg)
        return value


def validate_style_spec(style: Any) -> None:
    """Validate the structural shape of an inline style document."""
    if not isinstance(style, dict):
        msg = "style must be a JSON object"
        raise StyleValidationError(msg)
    try:
        _StyleSpec.model_validate(style)
    except pydantic.ValidationError as exc:
        raise StyleValidationError(str(exc)) from exc


def walk_tokens(value: Any):
    """Yield every string node in a JSON tree (dicts, lists, scalars)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_tokens(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_tokens(child)


def unknown_tokens(style: Any) -> set[str]:
    """Parameter token slugs referenced by the style (``{{slug}}`` nodes)."""
    tokens: set[str] = set()
    for node in walk_tokens(style):
        match = TOKEN_RE.match(node)
        if match:
            tokens.add(match.group(1))
    return tokens


def unknown_env_tokens(value: str) -> list[str]:
    """Return malformed ``{{env:NAME}}`` occurrences in a URL string.

    Well-formed tokens resolve server-side; anything that looks like an
    env token but does not match the strict pattern is reported.
    """
    strict = set(ENV_TOKEN_RE.findall(value))
    loose = re.findall(r"\{\{[^}]*env[^}]*\}\}", value, flags=re.IGNORECASE)
    return [t for t in loose if t not in {f"{{{{env:{name}}}}}" for name in strict}]


def validate_opacity_curve(expression: Any) -> None:
    """Validate an ``opacity-curve`` widget value (MapLibre expression).

    Expected shape: ``["interpolate", ["linear"], ["zoom"], z1, v1, ...]``
    with strictly ascending zoom stops and opacity outputs in [0, 1].
    """
    if not isinstance(expression, list) or len(expression) < 4:
        msg = "opacity curve must be an interpolate expression over zoom"
        raise StyleValidationError(msg)
    if expression[0] != "interpolate":
        msg = f"opacity curve must start with 'interpolate', got {expression[0]!r}"
        raise StyleValidationError(msg)
    if expression[2] != ["zoom"]:
        msg = f"opacity curve input must be ['zoom'], got {expression[2]!r}"
        raise StyleValidationError(msg)
    pairs = expression[3:]
    if len(pairs) % 2 != 0:
        msg = "opacity curve stops must be (zoom, value) pairs"
        raise StyleValidationError(msg)
    max_stops = 12
    if len(pairs) // 2 > max_stops:
        msg = f"opacity curve allows at most {max_stops} stops"
        raise StyleValidationError(msg)
    previous_zoom: float | None = None
    for zoom, opacity in zip(pairs[::2], pairs[1::2], strict=False):
        if not isinstance(zoom, (int, float)) or isinstance(zoom, bool):
            msg = f"opacity curve zoom stop must be a number, got {zoom!r}"
            raise StyleValidationError(msg)
        if previous_zoom is not None and zoom <= previous_zoom:
            msg = f"opacity curve zoom stops must be ascending at {zoom}"
            raise StyleValidationError(msg)
        if not isinstance(opacity, (int, float)) or isinstance(opacity, bool):
            msg = f"opacity curve value must be a number, got {opacity!r}"
            raise StyleValidationError(msg)
        if not 0 <= opacity <= 1:
            msg = f"opacity curve value must be within 0–1, got {opacity}"
            raise StyleValidationError(msg)
        previous_zoom = zoom


def local_hosts() -> set[str]:
    """Hosts considered first-party (no attribution requirement)."""
    hosts = {"localhost", "127.0.0.1"}
    tile_url = resolve_setting("MARTIN_TILE_URL")
    if tile_url:
        parsed = urlparse(tile_url)
        if parsed.hostname:
            hosts.add(parsed.hostname)
    return hosts


def has_external_sources(style: Any, local_hosts: set[str]) -> bool:
    """True when the style references any non-first-party source URL.

    Heuristic by design: raster/vector ``tiles`` templates, ``url``
    (TileJSON) entries and geojson ``data`` URLs are checked against the
    first-party host set. ``{{token}}`` placeholders are ignored — they
    resolve to first-party or client-managed URLs.
    """
    sources = style.get("sources", {}) if isinstance(style, dict) else {}
    for source in sources.values():
        if not isinstance(source, dict):
            continue
        for key in ("tiles",):
            entries = source.get(key) or []
            if isinstance(entries, str):
                entries = [entries]
            for entry in entries:
                if _is_external_url(entry, local_hosts):
                    return True
        for key in ("url", "data"):
            entry = source.get(key)
            if isinstance(entry, str) and _is_external_url(entry, local_hosts):
                return True
    return False


def _is_external_url(value: str, local_hosts: set[str]) -> bool:
    if not value or value.startswith("{{"):
        return False
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.hostname not in local_hosts


# ── Subset profile v0.1 (openspec style-profiles-subset, design D4) ────

#: Revision of the subset whitelist — the ``version`` recorded on
#: ``profile=subset`` rows. Widening the whitelist bumps this and rows
#: re-validate against the new rules.
SUBSET_REVISION = "0.1"

#: Allowed top-level style keys. ``glyphs``/``sprite`` may sit unused on
#: raster-only documents (the seeded raster styles carry one).
SUBSET_TOP_LEVEL_KEYS = frozenset(
    {"version", "name", "metadata", "sources", "sprite", "glyphs", "layers"}
)

#: Closed source key sets per type. ``encoding`` (value ``mlt``) is the
#: wodore/Martin MapLibre decoder marker — the one extension beyond the
#: stock style spec (unknown source keys are ignored by validators).
SUBSET_SOURCE_KEYS: dict[str, frozenset[str]] = {
    "raster": frozenset({"type", "tiles", "maxzoom", "tileSize", "attribution"}),
    "vector": frozenset(
        {"type", "tiles", "minzoom", "maxzoom", "attribution", "encoding"}
    ),
    "geojson": frozenset({"type", "data"}),
}

SUBSET_LAYER_TYPES = frozenset({"raster", "circle", "symbol"})

#: Permitted layer keys (minzoom/maxzoom carry the zoom gating).
SUBSET_LAYER_KEYS = frozenset(
    {"id", "type", "source", "source-layer", "minzoom", "maxzoom", "paint", "layout"}
)

#: Layout keys per layer type — circle/raster carry none; symbols get
#: "sprite-pack icon + simple text" positioning only (SDF text layout
#: props like variable anchors or letter spacing are out).
SUBSET_LAYOUT_KEYS: dict[str, frozenset[str]] = {
    "raster": frozenset(),
    "circle": frozenset(),
    "symbol": frozenset(
        {
            "icon-image",
            "icon-size",
            "icon-allow-overlap",
            "text-field",
            "text-font",
            "text-size",
            "text-anchor",
            "text-offset",
        }
    ),
}

#: Closed paint set. ``icon-size``/``text-size`` are layout properties in
#: the MapLibre spec but are accepted in either slot (design D4 — listed
#: once; the symbol layout whitelist carries them too).
SUBSET_PAINT_KEYS = frozenset(
    {
        "circle-color",
        "circle-radius",
        "circle-opacity",
        "circle-stroke-color",
        "circle-stroke-width",
        "raster-opacity",
        "raster-fade-duration",
        "icon-size",
        "icon-color",
        "icon-opacity",
        "icon-translate",
        "text-size",
        "text-color",
        "text-opacity",
        "text-halo-color",
        "text-halo-width",
        "text-translate",
    }
)

#: Recursive expression operator whitelist — ``interpolate`` accepts the
#: zoom input only (enforced in the walker, not just listed here).
SUBSET_EXPRESSION_OPS = frozenset(
    {"get", "has", "match", "case", "in", "==", "interpolate", "literal"}
)

#: MapLibre distinguishes expressions from literal array values by the
#: first element: a string that IS an operator name marks an expression
#: (``["feature-state", …]``), anything else (``["Noto Sans Regular"]``
#: for ``text-font``) is a literal array. The subset walker approximates
#: the operator-name test by shape — lowercase/hyphenated identifiers.
_OPERATOR_SHAPE_RE = re.compile(r"^[a-z][a-z0-9-]*$")

#: ``config.clustering`` shape (design D5) — renderer hints, never style
#: document content (``cluster`` is only legal on geojson sources in the
#: MapLibre spec; on a vector source it would break subset validity).
CLUSTERING_KEYS = frozenset(
    {"enabled", "source", "groupByProperty", "radius", "maxZoom", "bubble"}
)
CLUSTERING_BUBBLE_KEYS = frozenset(
    {"colorProperty", "iconProperty", "countProperty", "color", "icon"}
)


def _subset_error(errors: list[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message} (subset v{SUBSET_REVISION})")


def _check_subset_expression(value: Any, path: str, errors: list[str]) -> None:
    """Recursive whitelist check for one expression subtree.

    Strings pass (literals and standalone ``{{token}}`` parameter
    nodes); lists are expressions only when their first element looks
    like an operator name (MapLibre's own expression test, by shape) —
    other arrays are literal values (``text-font`` stacks, numeric
    pairs) and must contain scalars only; objects are never subset
    expressions. ``['linear']``/``['zoom']`` outside an ``interpolate``
    slot read as unknown operators — the error names the path, which
    is the point.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        if not value:
            return
        op = value[0]
        if not isinstance(op, str) or not _OPERATOR_SHAPE_RE.match(op):
            # Literal array value (font stacks, offsets, rgb triples) —
            # scalar entries only, never nested expressions.
            for index, entry in enumerate(value):
                if not (entry is None or isinstance(entry, (str, bool, int, float))):
                    _subset_error(
                        errors,
                        f"{path}[{index}]",
                        "literal array entries must be scalars "
                        "(nested expressions need an operator head)",
                    )
            return
        if op not in SUBSET_EXPRESSION_OPS:
            _subset_error(errors, path, f"operator {op!r} is not whitelisted")
            return
        if op == "interpolate":
            _check_subset_interpolate(value, path, errors)
            return
        for index, child in enumerate(value[1:], start=1):
            _check_subset_expression(child, f"{path}[{index}]", errors)
        return
    _subset_error(errors, path, "object expressions are not whitelisted")


def _check_subset_interpolate(expr: list[Any], path: str, errors: list[str]) -> None:
    """``['interpolate', ['linear'], ['zoom'], z, v, …]`` — zoom input only."""
    if len(expr) < 5 or len(expr) % 2 == 0:
        _subset_error(errors, path, "interpolate needs (zoom, value) stop pairs")
        return
    if expr[1] != ["linear"]:
        _subset_error(
            errors, f"{path}[1]", "only ['linear'] interpolation is whitelisted"
        )
    if expr[2] != ["zoom"]:
        _subset_error(errors, f"{path}[2]", "interpolate input must be ['zoom']")
    for index in range(3, len(expr), 2):
        stop = expr[index]
        if isinstance(stop, bool) or not isinstance(stop, (int, float)):
            _subset_error(
                errors, f"{path}[{index}]", "zoom stops must be literal numbers"
            )
        _check_subset_expression(expr[index + 1], f"{path}[{index + 1}]", errors)


def _is_string_list(value: Any) -> bool:
    if isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(entry, str) for entry in value)


def _check_subset_sources(style: dict[str, Any], errors: list[str]) -> None:
    sources = style.get("sources") or {}
    if not isinstance(sources, dict):
        _subset_error(errors, "sources", "must be an object")
        return
    for source_id, source in sources.items():
        path = f"sources.{source_id}"
        if not isinstance(source, dict):
            _subset_error(errors, path, "must be an object")
            continue
        source_type = source.get("type")
        if not isinstance(source_type, str) or source_type not in SUBSET_SOURCE_KEYS:
            _subset_error(
                errors,
                path,
                f"source type {source_type!r} is not whitelisted "
                f"(allowed: {', '.join(sorted(SUBSET_SOURCE_KEYS))})",
            )
            continue
        allowed = SUBSET_SOURCE_KEYS[source_type]
        for key in sorted(set(source) - allowed):
            _subset_error(errors, f"{path}.{key}", "source key is not whitelisted")
        tiles = source.get("tiles")
        if tiles is not None and not _is_string_list(tiles):
            _subset_error(
                errors, f"{path}.tiles", "must be a string or list of strings"
            )
        if source_type == "vector" and source.get("encoding") not in (None, "mlt"):
            _subset_error(
                errors, f"{path}.encoding", "only the value 'mlt' is whitelisted"
            )
        if source_type == "geojson" and not isinstance(source.get("data"), str):
            _subset_error(
                errors, f"{path}.data", "must be a data URL string (inline data is out)"
            )


def _check_subset_layers(style: dict[str, Any], errors: list[str]) -> None:
    for index, layer in enumerate(style.get("layers") or []):
        path = f"layers[{index}]"
        if not isinstance(layer, dict):
            _subset_error(errors, path, "must be an object")
            continue
        layer_type = layer.get("type")
        if not isinstance(layer_type, str) or layer_type not in SUBSET_LAYER_TYPES:
            _subset_error(
                errors,
                f"{path}.type",
                f"layer type {layer_type!r} is not whitelisted "
                f"(allowed: {', '.join(sorted(SUBSET_LAYER_TYPES))})",
            )
            continue
        for key in sorted(set(layer) - SUBSET_LAYER_KEYS):
            _subset_error(errors, f"{path}.{key}", "layer key is not whitelisted")
        layout = layer.get("layout") or {}
        allowed_layout = SUBSET_LAYOUT_KEYS.get(layer_type, frozenset())
        if isinstance(layout, dict):
            for key in sorted(set(layout) - allowed_layout):
                _subset_error(
                    errors, f"{path}.layout.{key}", "layout key is not whitelisted"
                )
            for key, value in layout.items():
                _check_subset_expression(value, f"{path}.layout.{key}", errors)
        else:
            _subset_error(errors, f"{path}.layout", "must be an object")
        paint = layer.get("paint") or {}
        if isinstance(paint, dict):
            for key in sorted(set(paint) - SUBSET_PAINT_KEYS):
                _subset_error(
                    errors, f"{path}.paint.{key}", "paint property is not whitelisted"
                )
            for key, value in paint.items():
                _check_subset_expression(value, f"{path}.paint.{key}", errors)
        else:
            _subset_error(errors, f"{path}.paint", "must be an object")


def validate_subset_style(style: Any) -> None:
    """Validate an inline style against the subset profile (v0.1).

    A subset document is a valid full MapLibre style by construction
    (structural checks run first) restricted to the whitelists above —
    renderable by a Leaflet-class engine. Raises
    :class:`StyleValidationError` with path-precise messages.
    """
    validate_style_spec(style)  # version 8, sources object, layer shapes
    errors: list[str] = []
    for key in sorted(set(style) - SUBSET_TOP_LEVEL_KEYS):
        _subset_error(errors, key, "top-level key is not whitelisted")
    _check_subset_sources(style, errors)
    _check_subset_layers(style, errors)
    if errors:
        raise StyleValidationError("; ".join(errors))


def validate_clustering_config(clustering: Any) -> None:
    """Shape-check a ``config.clustering`` block (design D5).

    Lightweight on purpose — known keys, value types, bubble carrying
    either property references or literal fallbacks. Property NAMES are
    free-form strings (they reference tile features, not this schema).
    """
    errors: list[str] = []
    if not isinstance(clustering, dict):
        raise StyleValidationError("clustering: must be an object")
    for key in sorted(set(clustering) - CLUSTERING_KEYS):
        errors.append(
            f"clustering.{key}: unknown key "
            f"(allowed: {', '.join(sorted(CLUSTERING_KEYS))})"
        )
    if "enabled" in clustering and not isinstance(clustering["enabled"], bool):
        errors.append("clustering.enabled: must be a boolean")
    for key in ("source", "groupByProperty"):
        if key in clustering and not isinstance(clustering[key], str):
            errors.append(f"clustering.{key}: must be a string")
    for key in ("radius", "maxZoom"):
        value = clustering.get(key)
        if key in clustering and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            errors.append(f"clustering.{key}: must be a number")
    bubble = clustering.get("bubble")
    if bubble is not None:
        if not isinstance(bubble, dict):
            errors.append("clustering.bubble: must be an object")
        else:
            for key in sorted(set(bubble) - CLUSTERING_BUBBLE_KEYS):
                errors.append(
                    f"clustering.bubble.{key}: unknown key "
                    "(property references or literal fallbacks only)"
                )
            for key, value in bubble.items():
                if not isinstance(value, str):
                    errors.append(f"clustering.bubble.{key}: must be a string")
    if errors:
        raise StyleValidationError("; ".join(errors))
