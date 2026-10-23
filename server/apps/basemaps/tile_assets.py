"""Tile asset versioning — the ``?v=`` source and serve-time injection.

Three kinds of versions feed one lookup (:func:`asset_versions`):

* **stored** — ``TileAssetVersion`` rows: ``sprites`` / ``fonts`` are
  published by the Martin watcher (:func:`run_martin_watcher`) from the
  bytes Martin *actually serves* (content-gated publication: a new
  version exists only once Martin serves new bytes, so the
  sync→restart window can never mint a version for old content).
  ``external`` rows are keyed by URL and bumped by the daily verifier
  (:func:`run_external_verifier`) or manually from the admin.
* **computed** — per-source tile versions derived at serve time from
  ``max(modified) + count()`` aggregates over each registered source's
  dependency tables (``VERSIONED_TILE_SOURCES``). Not stored: the
  database is the version source.
* the merged mapping is memoized (60 s) and consumed twice per style
  render: as the ``?v=`` values (:func:`inject_asset_versions`) and as
  part of the rendered-body cache key / ETag (see ``basemaps.api``).

Injection rules (spec: ``map-style-api`` "Caching and API contract"):
Martin-origin sprite URLs and the glyphs template get the
sprites/fonts version; tile URL templates whose first path segment is
a registered source get that source's version; registry-listed
external URLs get their entry's version. A URL is **never** touched
when it already carries a query string (``?``) or a ``{{double-brace}}``
parameter token — those URLs manage their own cache keys (e.g. the
availability source's ``?date={{date}}&days=4``). Single-brace MapLibre
tokens (``{z}``, ``{fontstack}``, ``{range}``) are part of the template
and are preserved.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlsplit

import structlog

from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models import Count, Max
from django.utils.timezone import now

from .models import MapLayer, TileAssetVersion

logger = structlog.get_logger("server.apps.basemaps")

#: Memo window for the merged version mapping (a freshness bound only —
#: an edit becomes visible on the next style render after expiry).
ASSET_VERSIONS_TTL = 60

#: Memo cache key (tests clear it after edits).
ASSET_VERSIONS_CACHE_KEY = "basemaps:asset-versions"

#: Probe timeout (seconds) for watcher/verifier fetches.
PROBE_TIMEOUT = 10

#: Several CDNs (maptoolkit fronts Cloudflare) reject the default
#: ``Python-urllib`` User-Agent with 403 — send a neutral custom one.
PROBE_USER_AGENT = "wodore-tile-asset-watcher/1.0 (+https://wodore.com)"

#: Glyph range probed per font stack (the first PBF range every
#: MapLibre text render requests; the style template carries the
#: ``.pbf`` extension itself).
FONT_PROBE_RANGE = "0-255"

#: Martin's static terrain postprocessing routes served as tiles —
#: watched like sprites/fonts (sample tile observed, hash published as a
#: stored ``tiles:<route>`` entry) so style references to them are
#: content-keyed without hand-bumped ``?v=N`` suffixes.
STATIC_TERRAIN_TILE_ROUTES = ("hillshade", "contours")

#: A representative Alpine tile used to probe the terrain routes
#: (coverage edge cases would 404 and keep the group unpublished —
#: safe, just unversioned).
TERRAIN_PROBE_TILE = (10, 540, 357)

#: Registered versioned Martin tile sources — opt-in, the single place
#: of policy. ``deps`` must cover every table the tile view/function
#: joins (unit-tested against ``HutsForTilesView.ViewMeta.query()``);
#: an edit to any dep rotates the version. Availability is deliberately
#: absent (self-rotating via ``?date=``); geoplaces is deferred until a
#: served style references it. Static terrain routes (hillshade,
#: contours) are versioned via watcher-observed stored entries instead.
VERSIONED_TILE_SOURCES: dict[str, dict[str, Any]] = {
    "huts": {
        "deps": (
            "huts.Hut",
            "categories.Category",
            "owners.Owner",
            "organizations.Organization",
            "huts.HutOrganizationAssociation",
        ),
    },
}


# ── Version lookup ────────────────────────────────────────────────────


def _computed_tile_versions() -> dict[str, str]:
    """Aggregate-derived version per registered tile source."""
    from django.apps import apps

    versions: dict[str, str] = {}
    for source, spec in VERSIONED_TILE_SOURCES.items():
        parts: list[str] = []
        for label in spec["deps"]:
            model = apps.get_model(label)
            agg = model.objects.aggregate(m=Max("modified"), c=Count("*"))
            stamp = agg["m"].isoformat() if agg["m"] else "-"
            parts.append(f"{label}:{agg['c']}:{stamp}")
        versions[source] = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return versions


def asset_versions(force: bool = False) -> dict[str, Any]:
    """Merged version mapping: stored rows + computed tile sources.

    Shape::

        {
            "sprites": "<hash>",            # stored, watcher-published
            "fonts": "<hash>",              # stored, watcher-published
            "tiles": {"huts": "<hash>"},    # computed from DB aggregates
            "external": {"<url-key>": "<hash>"},
        }

    Missing entries are absent (never ``None``): absent = unversioned.
    """
    from django.core.cache import cache

    def compute() -> dict[str, Any]:
        stored = {row.key: row for row in TileAssetVersion.objects.all()}
        tiles = _computed_tile_versions()
        # Stored static-route entries (``tiles:hillshade``, …) merge into
        # the same dict the injector reads — content-keyed terrain routes
        # without hand-bumped ``?v=N`` suffixes.
        for key, row in stored.items():
            if key.startswith("tiles:") and row.version:
                tiles[key.removeprefix("tiles:")] = row.version
        return {
            "sprites": stored["sprites"].version or None
            if "sprites" in stored
            else None,
            "fonts": stored["fonts"].version or None if "fonts" in stored else None,
            "tiles": tiles,
            "external": {
                row.key: row.version
                for row in TileAssetVersion.objects.filter(
                    origin=TileAssetVersion.Origin.external
                )
                if row.version
            },
        }

    if force:
        return compute()
    cached = cache.get_or_set(ASSET_VERSIONS_CACHE_KEY, compute, ASSET_VERSIONS_TTL)
    # ``compute`` always yields a dict; the isinstance guard only
    # satisfies the type checker's ``Any | None`` on get_or_set.
    return dict(cached) if isinstance(cached, dict) else compute()


def version_digest(versions: dict[str, Any]) -> str:
    """Stable short digest of a version mapping — cache-key component.

    Equal mappings ⇒ equal digest; any published/aggregate change ⇒
    different digest (rendered-body cache keys rotate).
    """
    return hashlib.sha256(
        json.dumps(versions, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


# ── Serve-time injection ──────────────────────────────────────────────


def _tile_origin() -> str:
    return (getattr(settings, "MARTIN_TILE_URL", "") or "").rstrip("/")


def _versionable(url: str) -> bool:
    """A URL may get a ``?v=`` only if it self-manages no cache key."""
    return not ("?" in url or "{{" in url)


def _append_param(url: str, value: str) -> str:
    return f"{url}?v={value}"


def _normalize_probe_url(url: str, origin: str) -> tuple[str, bool]:
    """(path, is_martin) for an authored OR resolved asset URL.

    Accepts the three authored shapes — ``{TILE_SERVER_URL}/…``
    placeholder, root-relative ``/…`` (Martin) and absolute URLs — plus
    the resolved absolute ones. Martin URLs are identified by the
    placeholder/root-relative forms or an absolute URL on the tile
    origin; other absolute URLs are external candidates.
    """
    url = url.replace("{TILE_SERVER_URL}", origin)
    if url.startswith("/"):
        return url, True
    split = urlsplit(url)
    if split.scheme in ("http", "https"):
        is_martin = bool(origin) and url.startswith(origin)
        return split.path, is_martin
    # No scheme, not root-relative (e.g. relative junk) — treat as
    # external candidate with the raw string as path.
    return url, False


def _match_asset(
    url: str, versions: dict[str, Any], origin: str
) -> tuple[str, str, str] | None:
    """(category, key, version) a URL consumes, or None.

    Category is ``sprites`` / ``fonts`` (Martin sprite+glyph routes,
    key == category) or ``external`` (key == registry URL, matched on
    exact URL or a boundary-aware prefix — MapLibre's ``.json``/``.png``
    suffixes and sub-paths belong to the key, ``/sprite2`` does not
    belong to ``/sprite``).
    """
    if not _versionable(url):
        return None
    path, is_martin = _normalize_probe_url(url, origin)
    segments = [s for s in path.split("/") if s]
    if is_martin and segments and segments[0] in ("sprite", "sdf_sprite", "font"):
        category = "fonts" if segments[0] == "font" else "sprites"
        version = versions.get(category)
        return (category, category, version) if version else None
    if not is_martin and url.startswith(("https://", "http://")):
        for key, version in versions.get("external", {}).items():
            if url == key or url.startswith(f"{key}/") or url.startswith(f"{key}."):
                return ("external", key, version)
    return None


def _inject_one(url: str, versions: dict[str, Any], origin: str) -> str:
    """Version a single URL if a rule matches, else return unchanged."""
    if not isinstance(url, str) or not url:
        return url
    match = _match_asset(url, versions, origin)
    if match:
        return _append_param(url, match[2])
    return url


def _tile_source_version(url: str, versions: dict[str, Any], origin: str) -> str | None:
    """The registered version for a Martin tile URL template.

    First path segment is the key — either a computed DB-backed source
    (``VERSIONED_TILE_SOURCES``) or a stored static-route entry
    (``tiles:hillshade`` / ``tiles:contours``, watcher-observed).
    """
    if not _versionable(url):
        return None
    path, is_martin = _normalize_probe_url(url, origin)
    if not is_martin:
        return None
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    return versions.get("tiles", {}).get(segments[0])


def _tile_source_name(url: str, origin: str) -> str | None:
    """Tile-route name for a tile URL template, if any."""
    path, is_martin = _normalize_probe_url(url, origin)
    if not is_martin:
        return None
    segments = [s for s in path.split("/") if s]
    return segments[0] if segments else None


def inject_asset_versions(
    style: dict[str, Any], versions: dict[str, Any]
) -> dict[str, Any]:
    """Return a style tree with ``?v=`` appended to versioned asset URLs.

    Pure function, no I/O; the input tree is left untouched.
    """
    if (
        not any(versions.get(k) for k in ("sprites", "fonts"))
        and not versions.get("tiles")
        and not versions.get("external")
    ):
        return style
    origin = _tile_origin()
    out = dict(style)

    sprite = style.get("sprite")
    if isinstance(sprite, str):
        out["sprite"] = _inject_one(sprite, versions, origin)
    elif isinstance(sprite, list):
        out["sprite"] = [
            (
                {**entry, "url": _inject_one(entry["url"], versions, origin)}
                if isinstance(entry, dict) and isinstance(entry.get("url"), str)
                else entry
            )
            for entry in sprite
        ]

    glyphs = style.get("glyphs")
    if isinstance(glyphs, str):
        out["glyphs"] = _inject_one(glyphs, versions, origin)

    sources = style.get("sources")
    if isinstance(sources, dict):
        new_sources = dict(sources)
        for name, source in sources.items():
            if not isinstance(source, dict):
                continue
            changed = False
            # TileJSON links (``url``) — external registry match (e.g. the
            # maptoolkit TileJSON endpoints): versioning the link busts
            # clients' cached TileJSON when the provider changes it.
            source_url = source.get("url")
            if isinstance(source_url, str) and source_url:
                injected = _inject_one(source_url, versions, origin)
                if injected != source_url:
                    source = {**source, "url": injected}
                    changed = True
            tiles = source.get("tiles")
            if isinstance(tiles, list):
                new_tiles = []
                for tile in tiles:
                    if isinstance(tile, str):
                        version = _tile_source_version(tile, versions, origin)
                        if version:
                            new_tiles.append(_append_param(tile, version))
                            changed = True
                        else:
                            new_tiles.append(tile)
                    else:
                        new_tiles.append(tile)
                if changed:
                    source = {**source, "tiles": new_tiles}
            if changed:
                new_sources[name] = source
        out["sources"] = new_sources

    return out


def consumed_versions(
    style: dict[str, Any], versions: dict[str, Any]
) -> dict[str, Any]:
    """The subset of ``versions`` a style's asset URLs would consume.

    Mirrors :func:`inject_asset_versions` matching (placeholder-aware, so
    it runs on the AUTHORED style before resolution — absolutization
    preserves paths). Drives the per-style version digest in the style
    cache key / ETag: a version change only re-keys the styles that
    actually reference that asset group (a hut edit must not rotate
    basemap ETags).
    """
    origin = _tile_origin()
    used: dict[str, Any] = {"sprites": None, "fonts": None, "tiles": {}, "external": {}}

    sprite = style.get("sprite")
    entries = (
        sprite
        if isinstance(sprite, list)
        else ([{"url": sprite}] if isinstance(sprite, str) else [])
    )
    for entry in entries:
        url = entry.get("url") if isinstance(entry, dict) else None
        if not isinstance(url, str):
            continue
        match = _match_asset(url, versions, origin)
        if not match:
            continue
        category, key, version = match
        if category == "external":
            used["external"][key] = version
        else:
            used[category] = version

    if isinstance(style.get("glyphs"), str):
        match = _match_asset(style["glyphs"], versions, origin)
        if match:
            category, _key, version = match
            if category == "external":
                used["external"][match[1]] = version
            else:
                used[category] = version

    sources = style.get("sources")
    if isinstance(sources, dict):
        for source in sources.values():
            if not isinstance(source, dict):
                continue
            # TileJSON links mirror the injector's source-``url`` pass
            source_url = source.get("url")
            if isinstance(source_url, str) and source_url:
                match = _match_asset(source_url, versions, origin)
                if match and match[0] == "external":
                    used["external"][match[1]] = match[2]
            tiles = source.get("tiles")
            if not isinstance(tiles, list):
                continue
            for tile in tiles:
                if not isinstance(tile, str):
                    continue
                name = _tile_source_name(tile, origin)
                version = _tile_source_version(tile, versions, origin)
                if name and version:
                    used["tiles"][name] = version
                elif not name:
                    match = _match_asset(tile, versions, origin)
                    if match and match[0] == "external":
                        used["external"][match[1]] = match[2]
    return used


# ── Probe collection (what do the served styles actually fetch?) ──────


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _active_authored_styles() -> list[dict[str, Any]]:
    """Style documents of active, inline-authored layers (any variant)."""
    layers = MapLayer.objects.filter(is_active=True, style__isnull=False)
    return [layer.style for layer in layers if isinstance(layer.style, dict)]


def collect_font_stacks(styles: list[dict[str, Any]]) -> list[str]:
    """Font stacks referenced by ``text-font`` — sorted, deduped."""
    stacks: set[str] = set()
    for style in styles:
        for layer in style.get("layers", []) or []:
            if not isinstance(layer, dict):
                continue
            layout = layer.get("layout")
            if not isinstance(layout, dict):
                continue
            fonts = layout.get("text-font")
            if isinstance(fonts, str):
                stacks.add(fonts)
            elif isinstance(fonts, list):
                stacks.update(f for f in fonts if isinstance(f, str))
    return sorted(stacks)


def _sprite_probe_variants(url: str) -> list[str]:
    """The URLs Martin actually serves for one authored sprite base URL.

    MapLibre appends ``.json``/``.png`` (and ``@2x``) client-side — the
    extension-less base has no Martin handler (404). Probing the
    suffixed pair observes every spritesheet change (they regenerate
    together from the same SVGs).
    """
    if "." in url.rsplit("/", 1)[-1]:
        return [url]  # already concrete (never true for authored sprites)
    return [f"{url}.json", f"{url}.png"]


def collect_martin_probes() -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Concrete sprite URLs and glyph-range URLs to hash, from live styles.

    Martin-origin URLs only (root-relative refs are absolutized to the
    tile origin; other origins — maptoolkit, openfreemap — belong to the
    external registry, not the Martin watcher). Sprite entries expand to
    their served ``.json``/``.png`` variants — Martin has no handler for
    the extension-less base (404); the glyphs template is instantiated
    once per referenced font stack — font stacks come from the styles'
    ``text-font`` arrays because Martin serves glyphs under the fonts'
    internal names, not file names.
    """
    styles = _active_authored_styles()
    origin = _tile_origin()

    def to_martin_url(url: str) -> str | None:
        """Absolutize and keep only tile-origin URLs; None = external."""
        url = url.replace("{TILE_SERVER_URL}", origin)
        if url.startswith("/"):
            return f"{origin}{url}"
        if origin and url.startswith(origin):
            return url
        return None

    sprite_urls: set[str] = set()
    glyphs_templates: set[str] = set()
    for style in styles:
        sprite = style.get("sprite")
        entries = (
            sprite
            if isinstance(sprite, list)
            else ([{"url": sprite}] if isinstance(sprite, str) else [])
        )
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                resolved = to_martin_url(entry["url"])
                if resolved:
                    sprite_urls.update(_sprite_probe_variants(resolved))
        if isinstance(style.get("glyphs"), str):
            resolved = to_martin_url(style["glyphs"])
            if resolved:
                glyphs_templates.add(resolved)

    font_urls: set[str] = set()
    for template in glyphs_templates:
        for stack in collect_font_stacks(styles):
            # Percent-encode the stack for the probe request — font
            # names contain spaces ("Noto Sans Regular") and urllib
            # rejects raw spaces in URLs; browsers/MapLibre encode them.
            # ``text-font`` may be a data-driven EXPRESSION whose
            # non-font strings ("case", "literal", …) land in the
            # scraped set — they 404 on Martin and the watcher skips
            # them (fonts group is 404-tolerant).
            url = template.replace("{fontstack}", quote(stack, safe="")).replace(
                "{range}", FONT_PROBE_RANGE
            )
            if "{" not in url:
                font_urls.add(url)

    # Static terrain routes (hillshade/contours): probe a representative
    # Alpine tile per referenced route — the published hash content-keys
    # the style's tile URLs (replaces hand-bumped ``?v=N``).
    z, x, y = TERRAIN_PROBE_TILE
    terrain_urls: dict[str, set[str]] = {}
    for style in styles:
        sources = style.get("sources")
        if not isinstance(sources, dict):
            continue
        for source in sources.values():
            if not isinstance(source, dict):
                continue
            tiles = source.get("tiles")
            if not isinstance(tiles, list):
                continue
            for tile in tiles:
                if not isinstance(tile, str):
                    continue
                path, is_martin = _normalize_probe_url(tile, origin)
                segments = [s for s in path.split("/") if s]
                if not is_martin or not segments:
                    continue
                route = segments[0]
                if route not in STATIC_TERRAIN_TILE_ROUTES:
                    continue
                base = to_martin_url(tile) or tile.replace("{TILE_SERVER_URL}", origin)
                concrete = base
                for token, value in (
                    ("{z}", str(z)),
                    ("{x}", str(x)),
                    ("{y}", str(y)),
                ):
                    concrete = concrete.replace(token, value)
                if "{" not in concrete and concrete.startswith(("http://", "https://")):
                    terrain_urls.setdefault(route, set()).add(concrete)

    return (
        sorted(sprite_urls),
        sorted(font_urls),
        {route: sorted(urls) for route, urls in terrain_urls.items()},
    )


# ── Martin asset watcher ──────────────────────────────────────────────


def _nonce_url(url: str, nonce: str) -> str:
    """Append the cache-busting nonce (query join aware)."""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_wd_watch={nonce}"


def _fetch(
    url: str, nonce: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    """GET one URL with a cache-busting nonce; returns (status, body, headers).

    Non-2xx responses are RETURNED, not raised: ``urlopen`` raises
    ``HTTPError`` for every non-2xx status (including 304 — the verifier's
    conditional-GET fast path depends on seeing it), so the error is
    normalized back into the (status, body, headers) shape. Only actual
    network failures (DNS, timeout, refused) propagate.
    """
    headers = {"User-Agent": PROBE_USER_AGENT, **(headers or {})}
    request = urllib.request.Request(
        _nonce_url(url, nonce),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers.items())


def _group_hash(results: list[tuple[str, bytes]]) -> str:
    parts = [
        f"{url}:{hashlib.sha256(body).hexdigest()}" for url, body in sorted(results)
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _publish(key: str, version: str) -> bool:
    """Store a version if it differs; True when a new version was written."""
    row, _created = TileAssetVersion.objects.get_or_create(
        key=key,
        defaults={
            "version": version,
            "origin": TileAssetVersion.Origin.martin_sync,
        },
    )
    if _created or row.version != version:
        row.version = version
        row.origin = TileAssetVersion.Origin.martin_sync
        row.save(update_fields=["version", "origin", "modified"])
        logger.info(
            "tile-asset-version-published", key=key, version=version, created=_created
        )
        return True
    return False


def run_martin_watcher() -> dict[str, Any]:
    """Observe Martin's served sprites/fonts; publish on change.

    django-q2 entry point (``Schedule.func``) and the body of the
    ``martin_asset_watch`` command. Probes carry a per-run nonce so an
    nginx ``proxy_cache`` tier cannot serve the watcher stale bytes
    after a Martin restart. Any probe failure keeps the stored version
    for that group (conservative: publication requires a full, healthy
    observation).
    """
    from django.core.cache import cache

    nonce = secrets.token_hex(8)
    stats: dict[str, Any] = {"published": [], "kept": [], "failed": []}

    sprite_urls, font_urls, terrain_urls = collect_martin_probes()
    groups: list[tuple[str, list[str]]] = [
        ("sprites", sprite_urls),
        ("fonts", font_urls),
        *[(f"tiles:{route}", urls) for route, urls in sorted(terrain_urls.items())],
    ]
    for key, urls in groups:
        if not urls:
            stats["kept"].append(key)
            continue
        # Font stacks are scraped from ``text-font`` arrays, which may
        # be data-driven expressions carrying non-font strings
        # ("case", "literal") — those 404 on Martin and are skipped
        # instead of failing the group. Sprites and terrain sample
        # tiles stay strict: their URLs come from the style directly,
        # a 404 is real breakage.
        tolerate_404 = key == "fonts"
        results: list[tuple[str, bytes]] = []
        failed = False
        for url in urls:
            try:
                status, body, _headers = _fetch(url, nonce)
                if status == 404 and tolerate_404:
                    continue
                if status != 200:
                    raise urllib.error.URLError(f"HTTP {status}")
                results.append((url, body))
            except Exception as exc:
                failed = True
                logger.warning(
                    "tile-asset-probe-failed", key=key, url=url, error=str(exc)
                )
        if failed or not results:
            stats["failed"].append(key)
            continue
        if _publish(key, _group_hash(results)):
            stats["published"].append(key)
        else:
            stats["kept"].append(key)

    cache.delete(ASSET_VERSIONS_CACHE_KEY)
    logger.info("martin-asset-watch-done", **stats)
    return stats


# ── External asset verifier ───────────────────────────────────────────


#: External keys verified unconditionally — consumed by the OG
#: static-map renderer rather than by style documents (which is what
#: the referenced-check below walks).
ALWAYS_VERIFIED_EXTERNAL_PREFIXES = ("https://tile.opentopomap.org/",)


def _external_referenced(keys: set[str]) -> set[str]:
    """Registry external keys actually referenced by active layers."""
    referenced: set[str] = set()
    referenced.update(
        key for key in keys if key.startswith(ALWAYS_VERIFIED_EXTERNAL_PREFIXES)
    )
    layers = MapLayer.objects.filter(is_active=True)
    urls: set[str] = set()
    for layer in layers:
        if layer.style_url:
            urls.add(layer.style_url)
        if isinstance(layer.style, dict):
            urls.update(
                u
                for u in _walk_strings(layer.style)
                if isinstance(u, str) and u.startswith(("http://", "https://"))
            )
    for key in keys:
        if any(url == key or url.startswith(key) for url in urls):
            referenced.add(key)
    return referenced


def _probe_variants(key: str) -> list[str]:
    """Concrete probe URLs for an external key.

    Sprite URLs are authored extension-less (MapLibre appends
    ``.json``/``.png``); probing the bare key plus both variants observes
    exactly what clients fetch. Keys already ending in a file extension
    probe only themselves.
    """
    last = key.rsplit("/", 1)[-1]
    if "." in last:
        return [key]
    return [key, f"{key}.json", f"{key}.png"]


def run_external_verifier() -> dict[str, Any]:
    """Daily conditional-GET verification of external registry entries.

    One pass over the probe variants (key, ``.json``, ``.png`` — whatever
    exists): the stored validators are sent to every variant, so a 304
    from the resource a validator came from short-circuits the entry as
    unchanged; 200 bodies are hashed into the new version; variants that
    404 are skipped (extension-less sprite keys routinely 404 — only the
    MapLibre-suffixed URLs exist). No 200 at all (or a network failure)
    keeps the stored version. Entries not referenced by any active layer
    are skipped. A re-hash that lands on the identical version string is
    reported as unchanged (no redundant writes).
    """
    from django.core.cache import cache

    nonce = secrets.token_hex(8)
    stats: dict[str, Any] = {
        "changed": [],
        "unchanged": [],
        "failed": [],
        "skipped": [],
    }

    entries = list(
        TileAssetVersion.objects.filter(origin=TileAssetVersion.Origin.external)
    )
    referenced = _external_referenced({e.key for e in entries})
    for entry in entries:
        if entry.key not in referenced:
            stats["skipped"].append(entry.key)
            continue
        variants = _probe_variants(entry.key)
        validators = {
            "If-None-Match": entry.etag,
            "If-Modified-Since": entry.last_modified,
        }
        validators = {k: v for k, v in validators.items() if v}
        bodies: list[tuple[str, bytes]] = []
        any_304 = False
        new_etag = ""
        new_last_modified = ""
        try:
            for url in variants:
                status, body, response_headers = _fetch(url, nonce, headers=validators)
                if status == 304:
                    any_304 = True
                    # keep probing: a later variant may have changed even
                    # when an earlier one 304s (a recolor alters the .png
                    # while the .json index stays byte-identical)
                elif status == 200:
                    bodies.append((url, body))
                    new_etag = new_etag or response_headers.get("ETag", "")[:256]
                    new_last_modified = (
                        new_last_modified
                        or response_headers.get("Last-Modified", "")[:64]
                    )
                # other statuses (e.g. 404 on the bare key): variant skipped
        except Exception as exc:
            stats["failed"].append(entry.key)
            logger.warning("external-asset-probe-failed", key=entry.key, error=str(exc))
            continue
        if not bodies:
            if any_304:
                # Every variant answered 304 — nothing changed.
                stats["unchanged"].append(entry.key)
                entry.last_checked = now()
                entry.save(update_fields=["last_checked"])
            else:
                # No 200 and no 304 — the asset is unreachable (without
                # validators a 304 cannot happen, so no 200s means dead).
                stats["failed"].append(entry.key)
            continue
        version = _group_hash(bodies)
        entry.last_checked = now()
        if version == entry.version:
            stats["unchanged"].append(entry.key)
            entry.save(update_fields=["last_checked"])
            continue
        entry.version = version
        entry.etag = new_etag
        entry.last_modified = new_last_modified
        entry.save(update_fields=["version", "etag", "last_modified", "last_checked"])
        stats["changed"].append(entry.key)

    cache.delete(ASSET_VERSIONS_CACHE_KEY)
    logger.info("external-asset-verify-done", **stats)
    return stats


__all__ = [
    "ASSET_VERSIONS_CACHE_KEY",
    "ASSET_VERSIONS_TTL",
    "FONT_PROBE_RANGE",
    "VERSIONED_TILE_SOURCES",
    "asset_versions",
    "collect_font_stacks",
    "cleanup_og_maps",
    "collect_martin_probes",
    "consumed_versions",
    "inject_asset_versions",
    "run_external_verifier",
    "run_martin_watcher",
    "version_digest",
]


# ── OG static-map maintenance ────────────────────────────────────────

#: OG cards (server.apps.api.ogmap) are immutable JPEGs keyed by
#: parameter digest; key rotations orphan old files. Cards older than
#: this many days are deleted daily — the next request re-renders
#: on demand (~0.5-2 s).
OG_MAP_MAX_AGE_DAYS = 30


def cleanup_og_maps() -> dict[str, int]:
    """Delete OG static-map cards older than :data:`OG_MAP_MAX_AGE_DAYS`.

    django-q2 entry point; safe to run concurrently with renders (a
    deleted card simply re-renders on its next request).
    """
    import time

    directory = "ogmaps"
    try:
        _dirs, files = default_storage.listdir(directory)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return {"deleted": 0, "kept": 0}
    cutoff = time.time() - OG_MAP_MAX_AGE_DAYS * 24 * 3600
    deleted = kept = 0
    for filename in files:
        name = f"{directory}/{filename}"
        try:
            if default_storage.get_modified_time(name).timestamp() < cutoff:
                default_storage.delete(name)
                deleted += 1
            else:
                kept += 1
        except (FileNotFoundError, OSError):
            continue
    logger.info("og-map-cleanup-done", deleted=deleted, kept=kept)
    return {"deleted": deleted, "kept": kept}
