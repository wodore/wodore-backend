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
