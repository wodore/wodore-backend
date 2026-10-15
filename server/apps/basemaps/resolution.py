"""Style resolution: parameter tokens, env secrets, URL absolutization.

One resolver for both serving modes:

* **resolved** (default) — parameter tokens are replaced with the
  authored values (registry defaults overlaid with per-layer overrides),
  env secrets are substituted, root-relative sprite/glyph URLs are
  absolutized to the tile server. Output is a plain MapLibre style.
* **tokenized** — parameter tokens stay; env secrets are still resolved
  (server-side in both modes — API keys live in backend config, never
  as user parameters).

The client re-runs the same token walk with user overrides layered on
top of the authored values (most-specific-wins, see models.MapParameter).
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any
from urllib.parse import urljoin

from django.conf import settings

from .validation import ENV_TOKEN_RE, TOKEN_RE

PLACEHOLDER_RE = re.compile(r"\{TILE_SERVER_URL\}")
#: Inline ``{{slug}}`` occurrences inside longer strings (URL templates).
TOKEN_RE_INLINE = re.compile(r"\{\{([a-z0-9][a-z0-9_.\-]*)\}\}")


def resolve_tokens(value: Any, values: dict[str, Any]) -> Any:
    """Recursively replace ``"{{slug}}"`` nodes with resolved values.

    Whole-node tokens may be replaced by scalars OR entire expression
    subtrees; tokens embedded inside longer strings (URL templates like
    ``…/{{date}}.geojson``) are substituted inline with scalar values
    only. ``None`` values never substitute (runtime params without a
    serve default stay tokenized).
    """
    usable = {slug: val for slug, val in values.items() if val is not None}
    return _resolve_tokens(value, usable)


def _resolve_tokens(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = TOKEN_RE.match(value)
        if match and match.group(1) in values:
            return values[match.group(1)]
        if "{{" in value and values:
            return TOKEN_RE_INLINE.sub(
                lambda m: (
                    str(values[m.group(1)]) if m.group(1) in values else m.group(0)
                ),
                value,
            )
        # Unknown tokens pass through untouched (tokenized mode for
        # layers the client customizes; the model's clean() guards
        # authored styles).
        return value
    if isinstance(value, dict):
        return {key: _resolve_tokens(child, values) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve_tokens(child, values) for child in value]
    return value


def collect_env_names(value: Any) -> set[str]:
    """Names referenced by ``{{env:NAME}}`` tokens anywhere in a tree.

    Resolution is name-scoped on purpose: building a full settings map
    per string node made serving large styles pathologically slow
    (``str()`` of every uppercase Django setting × thousands of nodes).
    """
    names: set[str] = set()
    for node in _walk_strings(value):
        names.update(ENV_TOKEN_RE.findall(node))
    return names


def build_env(names: set[str], extra: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the given env names once (OS env ∪ Django settings)."""
    env = dict(extra or {})
    for name in names:
        if name in env:
            continue
        if name in os.environ:
            env[name] = os.environ[name]
        elif hasattr(settings, name):
            env[name] = str(getattr(settings, name))
    return env


def substitute_env(value: str, extra: dict[str, str] | None = None) -> str:
    """Resolve ``{{env:NAME}}`` tokens in a single string.

    Kept for single-string use (style URLs); tree serving goes through
    :func:`substitute_env_tree`, which resolves each name exactly once.
    """
    names = set(ENV_TOKEN_RE.findall(value))
    if not names:
        return value
    env = build_env(names, extra)
    return ENV_TOKEN_RE.sub(lambda m: env.get(m.group(1), m.group(0)), value)


def _absolutize_url(url: str, tile_server_url: str, api_url: str) -> str:
    """Absolutize one URL: placeholders first, then root-relative refs."""
    if api_url:
        trimmed = api_url.rstrip("/")
        url = url.replace("{{API_URL}}", trimmed).replace("{API_URL}", trimmed)
    if url.startswith("{{"):
        return url
    if url.startswith("/"):
        base = tile_server_url.rstrip("/")
        return f"{base}{url}"
    return url


def absolutize_urls(value: Any, tile_server_url: str, api_url: str = "") -> Any:
    """Absolutize root-relative sprite/glyph/tile URLs in a style tree.

    MapProxy/Martin-served styles use Martin-root-relative refs
    (``/font/{fontstack}/{range}.pbf``, ``/sprite/wd-maps``) that only
    work when Martin serves the style itself. Once the API serves it,
    they must point at the tile server origin (spec requirement
    'absolutization').
    """
    tile_server_url = PLACEHOLDER_RE.sub(tile_server_url.rstrip("/"), tile_server_url)
    if isinstance(value, str):
        replaced = PLACEHOLDER_RE.sub(tile_server_url.rstrip("/"), value)
        return _absolutize_url(replaced, tile_server_url, api_url)
    if isinstance(value, dict):
        return {
            key: absolutize_urls(child, tile_server_url, api_url)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [absolutize_urls(child, tile_server_url, api_url) for child in value]
    return value


def resolve_style(
    style: Any,
    parameter_values: dict[str, Any],
    *,
    tokenized: bool = False,
    api_url: str = "",
) -> dict[str, Any]:
    """Full serve-time pipeline for an owned style document.

    Order matters: env substitution may live inside parameter defaults,
    URL placeholders resolve to the tile server, and root-relative refs
    are absolutized last (tokens must survive untouched in tokenized
    mode — they never start with ``/``).
    """
    resolved = deepcopy(style)
    resolved = substitute_env_tree(resolved)
    if not tokenized:
        resolved = resolve_tokens(resolved, parameter_values)
    tile_server_url = getattr(settings, "MARTIN_TILE_URL", "") or ""
    resolved = absolutize_urls(resolved, tile_server_url, api_url=api_url)
    return resolved


def substitute_env_tree(value: Any, env: dict[str, str] | None = None) -> Any:
    """Substitute ``{{env:NAME}}`` tokens inside string nodes of a tree.

    ``env`` may be prebuilt via :func:`build_env`; when omitted it is
    derived from the tokens actually present (one pass, names only).
    """
    if env is None:
        env = build_env(collect_env_names(value))
    if not env:
        return value
    if isinstance(value, str):
        return ENV_TOKEN_RE.sub(lambda m: env.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {key: substitute_env_tree(child, env) for key, child in value.items()}
    if isinstance(value, list):
        return [substitute_env_tree(child, env) for child in value]
    return value


def _walk_strings(value: Any):
    """Yield every string node in a JSON tree (dicts, lists, scalars)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_strings(child)


def style_endpoint_url(slug: str, spec: str | None = None) -> str:
    """Canonical style endpoint path for a layer slug."""
    url = f"/v1/map/styles/{slug}.json"
    if spec:
        url = f"{url}?spec={spec}"
    return url


__all__ = [
    "absolutize_urls",
    "resolve_style",
    "resolve_tokens",
    "style_endpoint_url",
    "substitute_env",
    "substitute_env_tree",
    "urljoin",
]
