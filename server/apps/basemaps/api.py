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

All evolving documents share one caching contract: a strong ETag and
``Cache-Control: public, max-age=0, must-revalidate, stale-if-error``
— one online reload is guaranteed fresh, offline serves the stored
copy. Rendered bodies are cached keyed by the ETag (version-keyed ⇒
self-busting); there is no time-based page cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import wraps
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import pydantic
from dmr import NewHeader, Path, Query, modify
from dmr.routing import external_path, path
from pydantic import Field

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from server.apps.api.controller import ApiController, raise_not_found
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

#: Revalidate-always caching for evolving documents (api-conventions):
#: stored, but revalidated on every use — one online reload is fresh;
#: offline/origin-down may serve the stored copy for a day.
REVALIDATE_CACHE_CONTROL = "public, max-age=0, must-revalidate, stale-if-error=604800"

#: Memo window for the exact catalog version aggregate. The bound is a
#: freshness delay only — an edit becomes visible on reload once the
#: memo expires (next-reload semantics, never a longer window).
CATALOG_VERSION_TTL = 10

#: Cache key of the memoized catalog version (tests clear it after edits).
CATALOG_VERSION_CACHE_KEY = "basemaps:catalog-version"

#: Rendered-style body retention. Keys are version-keyed (modified +
#: asset-version digest) so entries fall out of reach on every edit; the
#: TTL merely bounds stranded entries from version churn.
STYLE_CACHE_TTL = 7 * 24 * 3600


def revalidate_headers() -> dict[str, NewHeader]:
    """``Cache-Control`` header spec for ``@modify(headers=...)``."""
    return {"Cache-Control": NewHeader(value=REVALIDATE_CACHE_CONTROL)}


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
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    return str(
        cache.get_or_set(CATALOG_VERSION_CACHE_KEY, compute, CATALOG_VERSION_TTL)
    )


def _layer_version(slug: str) -> str:
    """Version input for one layer detail response (any variant row)."""
    from django.db.models import Max

    modified = MapLayer.objects.filter(slug=slug).aggregate(m=Max("modified")).get("m")
    return modified.isoformat() if modified else ""


def etag_page(version_fn: Any) -> Any:
    """Conditional-request wrapper for dmr collection/detail views.

    Computes a strong ETag from the version function plus every query
    parameter and the resolved API version (the versioning middleware
    may transform pinned responses — its ``Vary`` header keeps shared
    caches honest). ``If-None-Match`` answers 304 without rendering;
    otherwise the rendered body is cached keyed by the ETag
    (version-keyed ⇒ self-busting — no time-based page cache).
    """

    def decorator(view: Any) -> Any:
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            version = version_fn(request, **kwargs)
            vary = "|".join(
                (
                    request.path,
                    version,
                    urlencode(sorted(request.GET.items())),
                    getattr(request, "api_version", "") or "",
                )
            )
            etag = f'"{hashlib.sha256(vary.encode()).hexdigest()[:20]}"'
            match = request.headers.get("If-None-Match") == etag
            if match:
                response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
            else:
                from django.core.cache import cache

                body = cache.get(f"basemaps:doc:{etag}")
                if body is None:
                    response = view(request, *args, **kwargs)
                    if response.status_code == HTTPStatus.OK:
                        cache.set(
                            f"basemaps:doc:{etag}",
                            response.content,
                            timeout=24 * 60 * 60,
                        )
                else:
                    response = HttpResponse(body, content_type="application/json")
            if match or response.status_code == HTTPStatus.OK:
                response.headers["ETag"] = etag
                response.headers["Cache-Control"] = REVALIDATE_CACHE_CONTROL
            return response

        return wrapped

    return decorator


def _collection_version(request: HttpRequest, **_: Any) -> str:
    return catalog_version()


def _detail_version(request: HttpRequest, slug: str = "", **_: Any) -> str:
    return _layer_version(slug)


# ── Resolved-layer serialization ──────────────────────────────────────


def _style_url(layer: MapLayer) -> str:
    """Serving URL of the resolved variant's style document."""
    if layer.style is not None:
        return style_endpoint_url(layer.slug, layer.spec)
    # Externally authored: resolve env tokens server-side (API keys
    # live in backend config and never reach the client as params).
    return substitute_env(layer.style_url or "")


def _resolved_entry(layer: MapLayer) -> dict[str, Any]:
    """One resolved layer as a wire-shaped dict (i18n active)."""
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
        "style_url": _style_url(layer),
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
    """Env registry edit: availability and catalog payloads may change.

    Signal receiver wired in ``BasemapsConfig.ready()`` (post_save /
    post_delete on ``envvars.EnvVar``); the registry row snapshot is
    invalidated by ``envvars.registry`` itself.
    """
    from django.core.cache import cache

    global _env_gated_warned
    _env_gated_warned = set()
    cache.delete(CATALOG_VERSION_CACHE_KEY)


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
        headers=revalidate_headers(),
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
        headers=revalidate_headers(),
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
    single — the response reports the served spec); ``?v=`` is a
    free-form cache buster the client may append.
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
        # Resolved mode bakes a serve-time default into runtime date
        # params — the cache key and ETag must rotate with the date, or
        # a cached body would serve yesterday's date until any other
        # key input changes (bounded now by STYLE_CACHE_TTL, but a day
        # of stale dates is still wrong).
        from django.utils import timezone as _tz

        if layer.layer_parameters.filter(
            parameter__kind=MapParameter.Kind.date
        ).exists():
            consumed = {**consumed, "date": _tz.localdate().isoformat()}
    digest = version_digest(consumed)

    cached = _style_cache_get(layer, tokenized, digest)
    if cached is not None:
        body, etag = cached
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
        else:
            response = HttpResponse(body, content_type="application/json")
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = REVALIDATE_CACHE_CONTROL
        response.headers["X-Map-Spec"] = layer.spec
        return response

    api_url = request.build_absolute_uri("/").rstrip("/")
    values = layer.authored_parameter_values()
    # Runtime date params get a serve-time default so the resolved style
    # stays fetchable (spec: 'Runtime-scope parameters … resolved mode
    # substitutes the declared default').
    from django.utils import timezone

    for link in layer.layer_parameters.select_related("parameter"):
        if (
            link.parameter.kind == MapParameter.Kind.date
            and values.get(link.parameter.slug) is None
        ):
            values[link.parameter.slug] = timezone.localdate().isoformat()

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
        _style_cache_set(layer, tokenized, body, etag, digest)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = REVALIDATE_CACHE_CONTROL
    response.headers["X-Map-Spec"] = layer.spec
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


def _style_cache_key(layer: MapLayer, tokenized: bool, digest: str = "") -> str:
    """Render cache key — version-bumped by ``modified`` and the
    asset-version digest (a published sprite/font/tile version change
    re-renders even when the layer row is untouched)."""
    return (
        f"basemaps:style:{layer.pk}:{layer.spec}:"
        f"{'tokenized' if tokenized else 'resolved'}:"
        f"{layer.modified.isoformat()}:{digest}"
    )


def _style_cache_get(
    layer: MapLayer, tokenized: bool, digest: str = ""
) -> tuple[str, str] | None:
    from django.core.cache import cache

    return cache.get(_style_cache_key(layer, tokenized, digest))


def _style_cache_set(
    layer: MapLayer,
    tokenized: bool,
    body: str,
    etag: str,
    digest: str = "",
) -> None:
    from django.core.cache import cache

    # No unbounded retention: the key embeds ``modified`` + the per-style
    # asset-version digest — any style/parameter/asset-version edit
    # changes the key — and a generous TTL bounds stranded entries from
    # version churn.
    cache.set(
        _style_cache_key(layer, tokenized, digest),
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
        etag_page(_collection_version)(MapLayersController.as_view()),
        name="map-layers",
    ),
    path(
        "layers/<str:slug>",
        etag_page(_detail_version)(MapLayerDetailController.as_view()),
        name="map-layer-detail",
    ),
    path(
        "slots",
        etag_page(_collection_version)(MapSlotsController.as_view()),
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
