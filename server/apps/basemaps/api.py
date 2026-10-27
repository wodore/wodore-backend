"""Map layer catalog, slots, Martin-parity view and style endpoints.

* ``GET /v1/map/layers`` — THE catalog (dmr controller): the generic
  collection envelope ``{"data": [...], "count": N}`` with exactly one
  **resolved** layer per slug. ``?spec=`` is what the client *wants*
  (the entry's ``spec`` reports what was served — exact → explicit
  chain → single, server-side); no ``variants[]`` arrays, no inline
  style documents. ``?lang=``, ``?role=``, ``?show=`` and sparse
  fieldsets (``fields[map_layers]=…``) narrow the response.
* ``GET /v1/map/layers/{slug}`` — one resolved layer (same shape as
  the collection entries), per-layer ETag.
* ``GET /v1/map/slots`` — the slot registry, generic collection
  envelope.
* ``GET /v1/map/catalog`` — Martin-parity debug view: ``styles`` map
  of slug → ``{name, path}`` with ``?spec=`` resolved into ``path``.
  No selector metadata — not an application data source.
* ``GET /v1/map/styles/{slug}.json`` — the style itself (plain Django
  view, hidden from the OpenAPI schema like other file endpoints):
  resolved by default (a plain MapLibre style for any client),
  ``?mode=tokenized`` keeps parameter tokens for customizing clients,
  ``?spec=`` selects the device-tier variant. ETag + 304.

Layers referencing ``{{env:…}}`` tokens the env registry
(``server.apps.envvars``) cannot resolve are gated out everywhere
(layers, detail, catalog, style endpoint — 404; the detail names the
unresolved variables): a style URL with a literal token would be
unusable upstream, so the layer is simply not part of this
deployment's catalog. Registry edits flip availability at runtime.

All evolving documents share one caching contract built on strong
ETags and no time-based page cache (rendered bodies are cached keyed
by the ETag — version-keyed, self-busting):

* **Catalog documents** (``layers``, ``slots``): ``Cache-Control:
  public, max-age=0, must-revalidate, s-maxage=60, stale-if-error`` —
  browsers revalidate on every use (one online reload is guaranteed
  fresh; offline serves the stored copy), while the CDN edge may
  serve its copy for up to 60 s. The edge hit rate is what removes
  the map-boot round trips; a catalog ≤ 60 s stale is safe.
* **Style documents** are additionally version-keyed: every layer
  entry exposes ``style_version`` (and ``style_url`` already carries
  it as ``?v=``), and a style request whose ``?v=`` matches the
  current token is served ``Cache-Control: public, max-age=31536000,
  immutable`` — the token folds every content input (row ``modified``,
  consumed asset versions, env-registry epoch, the serve-time values
  of volatile parameters — ``Kind.is_volatile``), so the URL changes
  exactly when the content does. This is safe wherever the cache key
  includes the query string — the hub CDN zone provably does. A stale
  or missing ``?v=`` keeps the catalog policy: current, correct
  content, just revalidated; the current token is always visible in the
  ``X-Map-Style-Version`` response header.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from http import HTTPStatus
from typing import Any

import pydantic
from dmr import Path, Query, modify
from dmr.routing import external_path, path
from pydantic import Field

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from server.apps.api.controller import (
    IMMUTABLE_CACHE_CONTROL,
    REVALIDATE_CACHE_CONTROL,
    REVALIDATE_EDGE_CACHE_CONTROL,
    ApiController,
    edge_revalidate_headers,
    etag_page,
    raise_not_found,
    revalidate_headers,
)
from server.apps.api.error_codes import ErrorCode
from server.apps.api.query import dump_sparse, dump_sparse_list, sparse_fields_query
from server.apps.translations import LanguageQuery, override

from .models import (
    MapLayer,
    MapLayerAttribution,
    MapLayerCategory,
    MapLayerParameter,
    MapLegend,
    MapLegendItem,
    MapLegendLink,
    MapLegendSection,
    MapParameter,
    MapSlot,
)
from .resolution import resolve_style, style_endpoint_url, substitute_env

logger = logging.getLogger(__name__)

#: Memo window for the exact catalog version aggregate. The bound is a
#: freshness delay only — an edit becomes visible on reload once the
#: memo expires (next-reload semantics, never a longer window).
CATALOG_VERSION_TTL = 10

#: Cache key of the memoized catalog version (tests clear it after edits).
CATALOG_VERSION_CACHE_KEY = "basemaps:catalog-version"

#: Render epoch of cached style bodies — derived from the env
#: registry's content and memoized: registry values are baked into
#: rendered bodies (``{{env:...}}`` tokens via substitution, including
#: the tile origin's ``{{env:MARTIN_TILE_URL}}``), so every registry
#: change must re-key them. DB-derived on purpose — the default cache is
#: process-local (LocMemCache), so a signal bump would never reach the
#: other gunicorn workers; every worker derives the same value from
#: the DB and converges within the memo window.
STYLE_BODIES_EPOCH_KEY = "basemaps:style-bodies-epoch"

#: Freshness bound of the epoch memo — same bound as the registry row
#: snapshot (``envvars.registry.SNAPSHOT_TTL``).
STYLE_BODIES_EPOCH_TTL = 10

#: Rendered-style body retention. Keys are version-keyed (modified +
#: asset-version digest + registry epoch) so entries fall out of reach
#: on every edit; the TTL merely bounds stranded entries from version
#: churn.
STYLE_CACHE_TTL = 7 * 24 * 3600


# ── Query models ───────────────────────────────────────────────────────


class MapStylesQuery(LanguageQuery):
    """Query params for the Martin-parity catalog view."""

    spec: str | None = Field(
        None,
        description="Device-tier spec (low | medium | high); resolved into path",
        pattern="^(low|medium|high)$",
    )


class MapLayerEntry(pydantic.BaseModel):
    """One RESOLVED layer — the served variant, never a variant array.

    Spec-scoped fields (``spec``, ``style_url``, ``parameters``,
    ``attributions``, ``legend``, ``config``, ``interaction``,
    ``anchors``) serialize from the resolved variant row; identity
    fields are slug-scoped. All fields except ``slug`` are optional so
    sparse fieldsets can narrow the entry.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    # Identity (slug-scoped)
    slug: str
    role: str = ""
    name: str = ""
    description: str = ""
    icon: str = ""
    icon_badge: str = ""
    slot: str | None = None
    order: int = 0
    show: bool = True
    is_default: bool = False
    min_zoom: float | None = None
    max_zoom: float | None = None
    coverage_bbox: list[float] | None = None
    fallback_min_zoom: float | None = None
    fallback: str | None = None
    preview_url: str | None = None

    # Served variant (spec-scoped)
    spec: str = ""
    style_url: str = ""
    style_version: str | None = Field(
        None,
        description=(
            "Version token of this layer's style documents. Append it as "
            "``v`` to ANY style URL variant of this layer "
            "(``/v1/map/styles/{slug}.json?spec=…&mode=tokenized&v=<token>``) "
            "to receive an immutable, CDN- and browser-cacheable response. "
            "``style_url`` already carries it for the served variant. "
            "null for externally authored styles (nothing to version)."
        ),
    )
    modified: str = ""

    # Rich metadata (spec-scoped; resolved row)
    config: dict[str, Any] | None = None
    interaction: dict[str, Any] | None = None
    anchors: dict[str, Any] | None = None
    parameters: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    attributions: list[dict[str, Any]] = []
    license: dict[str, Any] | None = None
    legend: dict[str, Any] | None = None


class MapLayersEnvelope(pydantic.BaseModel):
    """Generic collection envelope (api-conventions)."""

    data: list[dict[str, Any]]
    count: int


MapLayerFields = sparse_fields_query(map_layers=MapLayerEntry)


class LayersQuery(LanguageQuery, MapLayerFields):
    """Query parameters for the layers collection."""

    spec: str | None = Field(
        None,
        description=(
            "Device-tier spec the client WANTS (low | medium | high); "
            "the backend resolves exact → explicit chain → single and "
            "reports the served spec per entry"
        ),
        pattern="^(low|medium|high)$",
    )
    role: str | None = Field(
        None,
        description="Filter by layer role (basemap | overlay)",
        pattern="^(basemap|overlay)$",
    )
    show: bool | None = Field(
        None,
        description=(
            "Opt-in visibility filter (true | false). Default: all "
            "layers — hidden fallback basemaps stay resolvable for "
            "client-side fallback chains"
        ),
    )


class SlotsQuery(LanguageQuery):
    """Query parameters for the slots collection."""


class LayerPath(pydantic.BaseModel):
    """Path params for the layer detail endpoint."""

    slug: str


# ── Catalog version + conditional caching ─────────────────────────────


def _catalog_version_models() -> tuple[type, ...]:
    """Every model the layers/slots/catalog payloads serialize.

    Including the env registry (``envvars.EnvVar``): registry edits
    change resolved ``style_url``s and layer availability, so they must
    rotate the catalog version. Imports live in the function to keep
    the app-import graph lean.
    """
    from server.apps.categories.models import Category
    from server.apps.envvars.models import EnvVar
    from server.apps.licenses.models import License
    from server.apps.organizations.models import Organization

    return (
        MapLayer,
        MapSlot,
        MapParameter,
        MapLegend,
        MapLegendSection,
        MapLegendItem,
        MapLegendLink,
        MapLayerCategory,
        MapLayerParameter,
        MapLayerAttribution,
        Category,
        EnvVar,
        Organization,
        License,
    )


def catalog_version() -> str:
    """Exact version of everything the catalog payloads serialize.

    ``max(modified)`` catches edits, the row count catches deletes —
    one aggregate per table, memoized for ``CATALOG_VERSION_TTL``
    seconds (a freshness bound, not a staleness window: the memo only
    delays an edit's visibility by at most the TTL). Every versioned
    model here is TimeStamped (``Category`` included since its
    timestamps landed); non-TimeStamped in-place edits are no longer a
    documented limitation.
    """
    from django.core.cache import cache
    from django.db.models import Max

    def compute() -> str:
        parts = []
        for model in _catalog_version_models():
            agg: dict[str, Any] = {"c": model.objects.count()}
            # Every serialized model is TimeStamped now (Category gained
            # created/modified with the tile-asset-versioning change); the
            # field check stays as a guard for future non-versioned
            # additions (count-only there).
            if "modified" in {f.name for f in model._meta.get_fields()}:
                agg["m"] = model.objects.aggregate(m=Max("modified"))["m"]
            stamp = agg["m"].isoformat() if agg.get("m") else "-"
            parts.append(f"{model.__name__}:{agg['c']}:{stamp}")
        # The entries embed per-layer style version tokens whose inputs
        # (registry epoch, asset versions, volatile-kind clocks) are not
        # table aggregates — fold them in, or a cached catalog body (24 h
        # keyed by this ETag, plus 60 s at the edge) would keep handing
        # out stale tokens. A stale token never yields wrong content — the
        # style endpoint verifies it before stamping immutable — but it
        # would silently lose the immutable edge caching.
        from .tile_assets import asset_versions, version_digest

        parts.append(f"epoch:{_style_bodies_epoch()}")
        parts.append(f"assets:{version_digest(asset_versions())}")
        for kind in MapParameter.Kind:
            served = kind.serve_time_value()
            if served is not None:
                parts.append(f"serve_time:{kind}:{served}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    return str(
        cache.get_or_set(CATALOG_VERSION_CACHE_KEY, compute, CATALOG_VERSION_TTL)
    )


def _layer_version(slug: str) -> str:
    """Version input for one layer detail response (any variant row).

    The detail body embeds the layer's ``style_version`` token, whose
    inputs (registry epoch, asset versions, volatile clocks) are not
    row attributes — fold them in like ``catalog_version`` does, or
    the 24 h ETag-keyed body cache would keep serving a stale token
    after an asset publish or registry edit (stale token ⇒ missed
    immutable caching, never wrong content: the style endpoint
    verifies the token before stamping immutable).
    """
    from django.db.models import Max

    from .tile_assets import asset_versions, version_digest

    modified = MapLayer.objects.filter(slug=slug).aggregate(m=Max("modified")).get("m")
    parts = [modified.isoformat() if modified else ""]
    parts.append(_style_bodies_epoch())
    parts.append(version_digest(asset_versions()))
    serve_time: dict[str, str] = {}
    for layer in MapLayer.objects.filter(slug=slug).prefetch_related(
        "layer_parameters__parameter"
    ):
        serve_time.update(layer.serve_time_parameter_values())
    if serve_time:
        parts.append(repr(sorted(serve_time.items())))
    return "|".join(parts)


def _collection_version(_request: HttpRequest, **_: Any) -> str:
    return catalog_version()


def _detail_version(_request: HttpRequest, slug: str = "", **_: Any) -> str:
    return _layer_version(slug)


# ── Resolved-layer serialization ──────────────────────────────────────


def _style_url(layer: MapLayer, token: str | None = None) -> str:
    """Serving URL of the resolved variant's style document.

    Owned styles carry the layer's ``?v=`` version token (immutable,
    self-busting at every cache that keys the query string — the hub
    CDN zone provably does); externally authored styles resolve env
    tokens server-side and stay unversioned (their target is not ours
    to version).
    """
    if layer.style is not None:
        url = style_endpoint_url(layer.slug, layer.spec)
        if token is None:
            token = style_version(layer)
        if token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}v={token}"
        return url
    # Externally authored: resolve env tokens server-side (API keys
    # live in backend config and never reach the client as params).
    return substitute_env(layer.style_url or "")


def style_version(
    layer: MapLayer,
    *,
    versions: dict[str, Any] | None = None,
    epoch: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """URL version token for one layer's style documents (``?v=``).

    ``None`` for externally authored styles — nothing of ours to
    version. The token is the identity of the style CONTENT behind
    the URL: it folds every input the rendered bodies depend on (the
    row's ``modified``, the asset-version groups the style consumes,
    the env-registry epoch) and, for layers with volatile parameters
    (``Kind.is_volatile`` — e.g. the runtime ``date``), the serve-time
    value: the resolved body bakes it in, so its immutable URL must
    rotate on the value's clock (this over-rotates the tokenized twin,
    which is harmless: a fresh URL, never a stale body). Mode-agnostic
    on purpose: tokenized and resolved variants share the token —
    they are distinct URLs (``mode`` query) with distinct cache
    entries, re-keyed by the same inputs.

    Must be computed from the same memoized ``versions``/``epoch`` as
    the body render in a request (see ``get_map_style``) so an
    immutable stamp can never pair a token with a body it does not
    describe. ``now`` pins the volatile clocks for tests.
    """
    if layer.style is None:
        return None

    from .tile_assets import asset_versions, consumed_versions, version_digest

    if versions is None:
        versions = asset_versions()
    if epoch is None:
        epoch = _style_bodies_epoch()
    consumed = consumed_versions(layer.style, versions)
    serve_time = layer.serve_time_parameter_values(now)
    if serve_time:
        consumed = {**consumed, **serve_time}
    source = "|".join(
        (
            str(layer.pk),
            layer.spec,
            layer.modified.isoformat(),
            version_digest(consumed),
            epoch,
        )
    )
    return hashlib.sha256(source.encode()).hexdigest()[:12]


def _resolved_entry(layer: MapLayer) -> dict[str, Any]:
    """One resolved layer as a wire-shaped dict (i18n active)."""
    token = style_version(layer)
    coverage_bbox = None
    if layer.coverage and layer.coverage.bbox:
        coverage_bbox = list(layer.coverage.bbox)

    parameters = [
        {
            "slug": link.parameter.slug,
            "kind": link.parameter.kind,
            "label": link.parameter.label_i18n,  # noqa: WPS308
            "description": link.parameter.description_i18n,  # noqa: WPS308
            "default": link.default_override
            if link.default_override is not None
            else link.parameter.default,
            "constraints": link.parameter.constraints,
        }
        for link in layer.layer_parameters.all()
    ]

    categories = [
        _category_projection(link.category, link.use, link.order)
        for link in layer.layer_categories.all()
        if link.category.is_active
    ]

    attributions = [
        {
            "name": link.organization.name_i18n or link.organization.name,
            "attribution": link.organization.attribution_i18n
            or link.organization.attribution,
            "url": link.organization.url,
        }
        for link in layer.layer_attributions.all()
    ]

    license_payload = None
    if layer.license:
        license_payload = {
            "name": layer.license.name_i18n or layer.license.name,  # noqa: WPS308
            "url": layer.license.url,
        }

    return {
        "slug": layer.slug,
        "role": layer.role,
        "name": layer.name_i18n or layer.name,  # noqa: WPS308
        "description": layer.description_i18n or layer.description or "",  # noqa: WPS308
        "icon": layer.icon or "",
        "icon_badge": layer.icon_badge or "",
        "slot": layer.slot.slug if layer.slot else None,
        "order": layer.order,
        "show": layer.show,
        "is_default": layer.is_default,
        "min_zoom": layer.min_zoom,
        "max_zoom": layer.max_zoom,
        "coverage_bbox": coverage_bbox,
        "fallback_min_zoom": layer.fallback_min_zoom,
        "fallback": layer.fallback.slug if layer.fallback else None,
        "preview_url": layer.preview_url or None,
        "spec": layer.spec,
        "style_url": _style_url(layer, token),
        "style_version": token,
        "modified": layer.modified.isoformat(),
        "config": layer.config,
        "interaction": layer.interaction,
        "anchors": layer.anchors,
        "parameters": parameters,
        "categories": categories,
        "attributions": attributions,
        "license": license_payload,
        "legend": _legend_payload(layer),
    }


def _legend_payload(layer: MapLayer) -> dict[str, Any] | None:
    """Serialize the resolved row's legend (frontend-compatible shape).

    Category-driven sections embed the minimal category projection;
    static items carry colors/widths verbatim — ``{{param}}`` tokens
    pass through so clients resolve them with the same defaults ∪
    user-overrides walk they use for styles (variable-aware legends).
    """
    legend = layer.legend
    if legend is None:
        return None
    sections: list[dict[str, Any]] = []
    for section in legend.sections.all():
        entry: dict[str, Any] = {
            "title": section.title_i18n or section.title,  # noqa: WPS308
            "description": section.description_i18n  # noqa: WPS308
            or section.description,
            "type": section.type,
        }
        if section.category_id and section.category is not None:  # type: ignore  # dynamic attr: plugin-less inference gap
            entry["category"] = _category_projection(
                section.category, "legend", section.order
            )
        else:
            entry["items"] = [
                {
                    "label": item.label_i18n or item.label,  # noqa: WPS308
                    "description": item.description_i18n  # noqa: WPS308
                    or item.description,
                    "color": item.color,
                    "width": item.width,
                    "icon": item.icon,
                }
                for item in section.items.all()
            ]
        sections.append(entry)
    links = [
        {
            "name": join.link.label_i18n or join.link.label,  # noqa: WPS308
            "url": join.link.url,
        }
        for join in legend.legend_links.all()
    ]
    payload: dict[str, Any] = {"sections": sections}
    if links:
        payload["links"] = links
    return payload


def _category_projection(category: Any, use: str, order: int) -> dict[str, Any]:
    """Minimal stable category projection (spec D6 — no full DTO).

    Children included so level-aware legends/filters render without a
    second request. Symbol/color fields come straight from the row;
    media URL modes stay a categories-endpoint concern.
    """
    projection: dict[str, Any] = {
        "slug": category.slug,
        "identifier": category.identifier,
        "name": category.name_i18n or category.name,  # noqa: WPS308
        "color": category.color,
        "use": use,
        "order": order,
        "children": [],
    }
    # Iterate the (prefetched) children and filter in Python — calling
    # .filter() on a prefetched relation would issue a fresh query.
    for child in category.children.all():
        if not child.is_active:
            continue
        projection["children"].append(
            {
                "slug": child.slug,
                "identifier": child.identifier,
                "name": child.name_i18n or child.name,  # noqa: WPS308
                "color": child.color,
            }
        )
    return projection


#: (slug, missing names) pairs already warned about in this process —
#: registry edits reset the memo (see ``_registry_changed``).
_env_gated_warned: set[tuple[str, tuple[str, ...]]] = set()


def _env_servable(layers: list[MapLayer]) -> list[MapLayer]:
    """Drop layers whose ``{{env:…}}`` tokens the env registry cannot resolve.

    A layer referencing an unresolved environment variable would ship
    a style URL (or style document) with the literal token — unusable
    upstream. Such layers are treated as not present in this
    deployment: hidden from every catalog view, 404 on the style
    endpoint. Availability follows the env registry (``envvars``) and
    flips at runtime when an operator edits it.
    """
    servable: list[MapLayer] = []
    for layer in layers:
        missing = layer.missing_env()
        if not missing:
            servable.append(layer)
            continue
        key = (layer.slug, tuple(sorted(missing)))
        if key not in _env_gated_warned:
            _env_gated_warned.add(key)
            logger.warning(
                "Map layer %r not servable — unresolved environment variable(s): %s",
                layer.slug,
                ", ".join(sorted(missing)),
            )
    return servable


def _registry_changed(*_: object, **_kwargs: object) -> None:
    """Env registry edit: availability, catalog and style bodies change.

    Signal receiver wired in ``BasemapsConfig.ready()`` (post_save /
    post_delete on ``envvars.EnvVar``); the registry row snapshot is
    invalidated by ``envvars.registry`` itself. Signals are in-process
    only — the style-body epoch is DB-derived (see
    ``_style_bodies_epoch``), so the other workers re-key within the
    memo window on their own; deleting the epoch memo here just makes
    the editing worker immediate.
    """
    from django.core.cache import cache

    global _env_gated_warned
    _env_gated_warned = set()
    cache.delete(CATALOG_VERSION_CACHE_KEY)
    cache.delete(STYLE_BODIES_EPOCH_KEY)


def _prefetched_layers(**filters: Any) -> list[MapLayer]:
    """Active, servable layers with everything ``_resolved_entry`` serializes.

    One query for the rows + select_related FKs, one per prefetch path —
    ``_resolved_entry``/``_legend_payload``/``_category_projection``
    read lazily otherwise (N+1 per layer/section/category).
    """
    from django.db.models import Prefetch

    from server.apps.categories.models import Category

    layers = list(
        MapLayer.objects.filter(is_active=True, **filters)
        .select_related("slot", "coverage", "license", "fallback")
        .prefetch_related(
            "layer_parameters__parameter",
            "layer_categories__category",
            "layer_attributions__organization",
            "legend__sections__items",
            "legend__sections__category",
            "legend__legend_links__link",
            Prefetch(
                "layer_categories__category__children",
                queryset=Category.objects.filter(is_active=True),
            ),
            Prefetch(
                "legend__sections__category__children",
                queryset=Category.objects.filter(is_active=True),
            ),
        )
        .order_by("role", "order", "slug", "spec")
    )
    return _env_servable(layers)


def _resolved_layers(layers: list[MapLayer], spec: str | None) -> list[dict[str, Any]]:
    """One resolved entry per slug (server-side spec resolution)."""
    by_slug: dict[str, list[MapLayer]] = {}
    for layer in layers:
        by_slug.setdefault(layer.slug, []).append(layer)
    resolved = [
        picked
        for picked in (MapLayer.pick_variant(group, spec) for group in by_slug.values())
        if picked is not None
    ]
    resolved.sort(key=lambda layer: (layer.role, layer.order, layer.slug))
    return [_resolved_entry(layer) for layer in resolved]


# ── Controllers ────────────────────────────────────────────────────────


class MapLayersController(ApiController):
    """The map layer catalog — one resolved layer per slug."""

    @modify(
        operation_id="map-layers",
        headers=edge_revalidate_headers(),
    )
    def get(
        self,
        parsed_query: Query[LayersQuery],
    ) -> MapLayersEnvelope:
        """List resolved map layers (generic collection envelope).

        The backend resolves the wanted ``spec`` per layer (exact →
        explicit chain → single) and reports the served tier — clients
        never select among variants. Sparse fieldsets narrow entries.
        """
        filters: dict[str, Any] = {}
        if parsed_query.role:
            filters["role"] = parsed_query.role
        if parsed_query.show is not None:
            filters["show"] = parsed_query.show
        with override(parsed_query.lang):
            entries = _resolved_layers(_prefetched_layers(**filters), parsed_query.spec)
        data = dump_sparse_list(
            MapLayerEntry, entries, parsed_query, "map_layers", "__all__"
        )
        return MapLayersEnvelope(data=data, count=len(data))  # type: ignore[arg-type]


class MapLayerDetailController(ApiController):
    """One resolved layer by slug."""

    @modify(
        operation_id="map-layer-detail",
        headers=revalidate_headers(),
    )
    def get(
        self,
        parsed_path: Path[LayerPath],
        parsed_query: Query[LayersQuery],
    ) -> dict[str, Any]:
        """Get one resolved layer (same shape as the collection entries).

        Per-layer ETag folds the layer's ``modified``, the served
        ``spec`` and ``lang`` — unchanged layers answer 304.
        """
        layer = MapLayer.pick_variant(
            _prefetched_layers(slug=parsed_path.slug), parsed_query.spec
        )
        if layer is None:
            raise_not_found(f"No active map layer with slug {parsed_path.slug!r}.")
        with override(parsed_query.lang):
            entry = _resolved_entry(layer)
        return dump_sparse(MapLayerEntry, entry, parsed_query, "map_layers", "__all__")  # type: ignore[no-any-return]


class MapSlotsController(ApiController):
    """The slot registry."""

    @modify(
        operation_id="map-slots",
        headers=edge_revalidate_headers(),
    )
    def get(
        self,
        parsed_query: Query[SlotsQuery],
    ) -> dict[str, Any]:
        """List map slots (generic collection envelope)."""
        with override(parsed_query.lang):
            data = [
                {
                    "slug": slot.slug,
                    "label": slot.label_i18n or slot.label,  # noqa: WPS308
                    "order": slot.order,
                }
                for slot in MapSlot.objects.order_by("order", "slug")
            ]
        return {"data": data, "count": len(data)}


class MapCatalogController(ApiController):
    """Martin-compatible catalog — parity debug view, not app data."""

    @modify(
        operation_id="map-catalog",
        headers=revalidate_headers(),
    )
    def get(
        self,
        parsed_query: Query[MapStylesQuery],
    ) -> dict[str, Any]:
        """Martin-parity catalog: slug → {name, path} only."""
        styles: dict[str, Any] = {}
        with override(parsed_query.lang):
            for entry in _resolved_layers(_prefetched_layers(), parsed_query.spec):
                styles[entry["slug"]] = {
                    "name": entry["name"],
                    "path": entry["style_url"],
                }
        return {"styles": styles}


# ── Style endpoint (plain view, hidden from the OpenAPI schema) ───────


def get_map_style(request: HttpRequest, slug: str) -> HttpResponse:
    """Serve a layer style — resolved by default, tokenized opt-in.

    ``?spec=`` picks the device-tier variant (exact → explicit chain →
    single — the response reports the served spec); ``?v=`` with the
    layer's current ``style_version`` token (from ``/v1/map/layers`` or
    this endpoint's ``X-Map-Style-Version`` header) serves the response
    as immutable — the token changes exactly when the content does.
    A stale or missing token still serves the current content, under
    the bounded-staleness catalog policy.
    """
    layer = MapLayer.pick_variant(
        MapLayer.objects.filter(slug=slug), request.GET.get("spec")
    )
    if layer is None:
        return _style_error(
            f"No active map layer with slug {slug!r}.", HTTPStatus.NOT_FOUND
        )

    # Env-gated layer (unresolved ``{{env:…}}`` token in the registry):
    # never serve the broken pointer — report the layer as absent,
    # like the catalog.
    missing = layer.missing_env()
    if missing:
        return _style_error(
            f"Layer {slug!r} is not available in this deployment: unresolved "
            f"environment variable(s): {', '.join(sorted(missing))}.",
            HTTPStatus.NOT_FOUND,
        )

    tokenized = request.GET.get("mode") == "tokenized"

    if layer.style is None:
        # Externally authored style: redirect with env resolved.
        resolved_url = substitute_env(layer.style_url or "")
        if not resolved_url:
            return _style_error(
                f"Layer {slug!r} has neither style nor style_url.",
                HTTPStatus.NOT_FOUND,
            )
        response = HttpResponseRedirect(resolved_url)
        response.headers["Cache-Control"] = REVALIDATE_CACHE_CONTROL
        return response

    from .tile_assets import (
        asset_versions,
        consumed_versions,
        inject_asset_versions,
        version_digest,
    )

    versions = asset_versions()
    # Per-style digest: only the version groups this style's asset URLs
    # consume — a hut-data edit re-keys the huts overlay, not the
    # basemaps. Placeholder-aware, so it runs on the authored style
    # before resolution (absolutization preserves paths).
    consumed = consumed_versions(layer.style, versions)
    if not tokenized:
        # Resolved mode bakes serve-time values into volatile
        # parameters — the cache key and ETag must rotate with them, or
        # a cached body would serve yesterday's value until any other
        # key input changes (bounded now by STYLE_CACHE_TTL, but a day
        # of stale values is still wrong).
        serve_time = layer.serve_time_parameter_values()
        if serve_time:
            consumed = {**consumed, **serve_time}
    digest = version_digest(consumed)

    # One epoch per request: a registry edit landing between the cache
    # lookup and the store must not file a pre-edit body under the
    # post-edit epoch (it would survive the full STYLE_CACHE_TTL).
    epoch = _style_bodies_epoch()
    # Version-keyed immutability: a ``?v=`` matching the current token
    # makes the URL self-busting (token folds every content input), so
    # every cache may treat the response as permanently fresh. Computed
    # from the same request-pinned ``versions``/``epoch`` as the body
    # below — an immutable stamp can never pair a token with a body it
    # does not describe. Stale/missing token: current content under the
    # bounded-staleness catalog policy (s-maxage=60), never immutable.
    token = style_version(layer, versions=versions, epoch=epoch)
    versioned = token is not None and request.GET.get("v") == token
    cache_control = (
        IMMUTABLE_CACHE_CONTROL if versioned else REVALIDATE_EDGE_CACHE_CONTROL
    )
    cached = _style_cache_get(layer, tokenized, digest, epoch=epoch)
    if cached is not None:
        body, etag = cached
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
        else:
            response = HttpResponse(body, content_type="application/json")
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
        response.headers["X-Map-Spec"] = layer.spec
        if token:
            response.headers["X-Map-Style-Version"] = token
        return response

    api_url = request.build_absolute_uri("/").rstrip("/")
    values = layer.authored_parameter_values()
    # Volatile parameters get a serve-time value so the resolved style
    # stays fetchable (spec: 'Runtime-scope parameters … resolved mode
    # substitutes the declared default').
    for link in layer.layer_parameters.select_related("parameter"):
        if values.get(link.parameter.slug) is None:
            served = link.parameter.serve_time_value()
            if served is not None:
                values[link.parameter.slug] = served

    payload = resolve_style(
        layer.style,
        values,
        tokenized=tokenized,
        api_url=api_url,
    )
    # Serve-time asset versioning: ``?v=`` on Martin sprite/glyph/tile
    # URLs (and registry-listed external URLs) — the version digest is
    # folded into the cache key and the body content into the ETag, so
    # a published version change re-renders and busts on the next
    # conditional request.
    payload = inject_asset_versions(payload, versions)
    if not tokenized:
        payload = _inject_serving_metadata(payload, layer)

    body = json.dumps(payload, separators=(",", ":"))
    etag_source = "|".join(
        (
            slug,
            layer.spec,
            "tokenized" if tokenized else "resolved",
            str(layer.modified),
            digest,
            hashlib.sha256(body.encode()).hexdigest(),
        )
    )
    etag = f'"{hashlib.sha256(etag_source.encode()).hexdigest()}"'

    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
    else:
        response = HttpResponse(body, content_type="application/json")
        _style_cache_set(layer, tokenized, body, etag, digest, epoch=epoch)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = cache_control
    response.headers["X-Map-Spec"] = layer.spec
    if token:
        response.headers["X-Map-Style-Version"] = token
    return response


def _inject_serving_metadata(
    payload: dict[str, Any], layer: MapLayer
) -> dict[str, Any]:
    """Attach served-spec reporting + version (client cache sync)."""
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["wd:served_spec"] = layer.spec
        metadata["wd:slug"] = layer.slug
        metadata["wd:version"] = layer.modified.isoformat()
    return payload


def _style_bodies_epoch() -> str:
    """Current render epoch of style bodies, derived from the registry.

    Digest over every row's ``(name, value, is_active, env_fallback)``
    plus the row count, memoized — any conceivable registry edit changes
    it, every worker derives the identical value from the DB, and no
    cross-process signal is needed. Content-derived on purpose:
    ``modified`` timestamps proved unreliable as a change signal in
    this stack (observed regressing to the creation instant on
    ``update_or_create``), while a value edit is exactly what must
    re-key the bodies. Empty table → digest of the empty tuple.
    """
    from django.core.cache import cache

    epoch: str | None = cache.get(STYLE_BODIES_EPOCH_KEY)
    if epoch is None:
        from server.apps.envvars.models import EnvVar

        rows = list(
            EnvVar.objects.values_list(
                "name", "value", "is_active", "env_fallback"
            ).order_by("name")
        )
        digest = hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
        epoch = f"{digest}:{len(rows)}"
        cache.set(STYLE_BODIES_EPOCH_KEY, epoch, STYLE_BODIES_EPOCH_TTL)
    return epoch


def _style_cache_key(
    layer: MapLayer, tokenized: bool, digest: str = "", epoch: str | None = None
) -> str:
    """Render cache key — version-bumped by ``modified``, the
    asset-version digest (a published sprite/font/tile version change
    re-renders even when the layer row is untouched) and the registry
    epoch (registry values are baked into bodies at render time).

    ``epoch`` pins the epoch for one request (read once, reused for
    the cache get *and* set) — a registry edit landing mid-request
    must not file a pre-edit body under the post-edit epoch.
    """
    resolved = _style_bodies_epoch() if epoch is None else epoch
    return (
        f"basemaps:style:{layer.pk}:{layer.spec}:"
        f"{'tokenized' if tokenized else 'resolved'}:"
        f"{layer.modified.isoformat()}:{digest}:{resolved}"
    )


def _style_cache_get(
    layer: MapLayer, tokenized: bool, digest: str = "", *, epoch: str | None = None
) -> tuple[str, str] | None:
    from django.core.cache import cache

    return cache.get(_style_cache_key(layer, tokenized, digest, epoch))


def _style_cache_set(
    layer: MapLayer,
    tokenized: bool,
    body: str,
    etag: str,
    digest: str = "",
    *,
    epoch: str | None = None,
) -> None:
    from django.core.cache import cache

    # No unbounded retention: the key embeds ``modified`` + the per-style
    # asset-version digest + the registry epoch — any style/parameter/
    # asset-version/registry edit changes the key — and a generous TTL
    # bounds stranded entries from version churn.
    cache.set(
        _style_cache_key(layer, tokenized, digest, epoch),
        (body, etag),
        timeout=STYLE_CACHE_TTL,
    )


def _style_error(detail: str, status: HTTPStatus) -> HttpResponse:
    """Error body in the project-wide API shape."""
    from django.http import JsonResponse

    return JsonResponse(
        {"code": ErrorCode.not_found, "detail": detail},
        status=status,
    )


paths: list[Any] = [
    path(
        "layers",
        etag_page(_collection_version, REVALIDATE_EDGE_CACHE_CONTROL)(
            MapLayersController.as_view()
        ),
        name="map-layers",
    ),
    path(
        "layers/<str:slug>",
        etag_page(_detail_version)(MapLayerDetailController.as_view()),
        name="map-layer-detail",
    ),
    path(
        "slots",
        etag_page(_collection_version, REVALIDATE_EDGE_CACHE_CONTROL)(
            MapSlotsController.as_view()
        ),
        name="map-slots",
    ),
    path(
        "catalog",
        etag_page(_collection_version)(MapCatalogController.as_view()),
        name="map-catalog",
    ),
    external_path(
        "styles/<slug>.json",
        get_map_style,
        openapi=None,
        name="map-style",
    ),
]
