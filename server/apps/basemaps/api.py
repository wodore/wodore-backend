"""Map catalog and style endpoints.

* ``GET /v1/map/styles`` — Martin-compatible style index (dmr
  controller): flat map of style-slug → {path, name, icon, role,
  description, is_default}, plus tiles/sprites/fonts/settings sections.
  Supports ``?lang=`` and ``?spec=`` (self-resolves to nearest variant).
* ``GET /v1/map/config`` — rich map configuration (dmr controller,
  contract-tested): identity, i18n labels, icons, parameters with
  schemas, spec variants, category projections, coverage bounds,
  style URLs for big styles. Never inlines base style documents.
  The frontend basemap picker consumes this.
* ``GET /v1/map/styles/{slug}.json`` — the style itself (plain Django
  view, hidden from the OpenAPI schema like other file endpoints):
  resolved by default (a plain MapLibre style for any client),
  ``?mode=tokenized`` keeps parameter tokens for customizing clients,
  ``?spec=`` selects the device-tier variant (exact → nearest →
  single). ETag + 304 + Cache-Control.
"""

from __future__ import annotations

import hashlib
import json
import logging
from http import HTTPStatus
from typing import Any

import pydantic
from dmr import Query, modify
from dmr.routing import external_path, path
from pydantic import Field

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import cache_page

from server.apps.api.controller import ApiController, cache_headers
from server.apps.api.error_codes import ErrorCode
from server.apps.translations import LanguageQuery, override

from .models import MapLayer, MapParameter, MapSlot
from .resolution import resolve_style, style_endpoint_url, substitute_env

logger = logging.getLogger(__name__)

CACHE_MAX_AGE = 6 * 60 * 60  # 6 hours in seconds
#: Styles larger than this many bytes are never inlined in the catalog
#: (the entry carries the style endpoint URL instead).
INLINE_STYLE_MAX_BYTES = 8_192


class MapStylesQuery(LanguageQuery):
    """Query params for the Martin-compatible style index."""

    spec: str | None = Field(
        None,
        description="Device-tier spec (low | medium | high); self-resolves to nearest",
        pattern="^(low|medium|high)$",
    )


class MapCatalogQuery(LanguageQuery):
    """Query params for the catalog endpoint."""

    role: str | None = Field(
        None,
        description="Filter by layer role (basemap | overlay)",
        pattern="^(basemap|overlay)$",
    )


class ParameterSummary(pydantic.BaseModel):
    """Parameter schema entry (drives the client settings UI)."""

    model_config = pydantic.ConfigDict(extra="allow")

    slug: str
    kind: str
    label: str = ""
    description: str = ""
    default: Any = None
    constraints: dict[str, Any] | None = None


class LayerVariant(pydantic.BaseModel):
    """One device-tier variant of a layer."""

    model_config = pydantic.ConfigDict(extra="allow")

    spec: str
    style_url: str | None = None
    inline_style: dict[str, Any] | None = None


class LayerSummary(pydantic.BaseModel):
    """Catalog entry for one layer (all its variants share the identity)."""

    model_config = pydantic.ConfigDict(extra="allow")

    slug: str
    role: str
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
    anchors: dict[str, Any] | None = None
    preview_url: str | None = None
    config: dict[str, Any] | None = None
    interaction: dict[str, Any] | None = None
    parameters: list[ParameterSummary] = []
    categories: list[dict[str, Any]] = []
    attributions: list[dict[str, Any]] = []
    license: dict[str, Any] | None = None
    legend: dict[str, Any] | None = None
    version: str | None = None
    variants: list[LayerVariant] = []


class MapCatalogResponse(pydantic.BaseModel):
    """Top-level catalog payload."""

    slots: list[dict[str, Any]] = []
    layers: list[LayerSummary] = []


class MapStylesController(ApiController):
    """Martin-compatible style index — fast, lightweight, selector-ready.

    Returns a flat map of style-slug → entry with just enough metadata
    for a frontend selector (name, icon, role, is_default). Also includes
    tiles/sprites/fonts/settings sections matching Martin's catalog shape.
    Supports ``?lang=`` for localized names and ``?spec=`` for
    device-tier resolution (exact → nearest → single).
    """

    @modify(
        operation_id="map-styles-index",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(
        self,
        parsed_query: Query[MapStylesQuery],
    ) -> dict[str, Any]:
        """Martin-compatible style index."""
        queryset = MapLayer.objects.filter(is_active=True).select_related(
            "slot", "coverage", "license", "fallback"
        )

        styles: dict[str, Any] = {}
        with override(parsed_query.lang):
            for layer in queryset:
                if layer.slug in styles:
                    continue  # variants share identity; keep the first
                styles[layer.slug] = {
                    "path": style_endpoint_url(layer.slug),
                    "name": str(layer.name_i18n or layer.name),
                    "description": str(
                        layer.description_i18n or layer.description or ""
                    ),
                    "icon": layer.icon or "",
                    "role": layer.role,
                    "is_default": layer.is_default,
                }

        return {
            "tiles": {},  # served by Martin, not the backend
            "sprites": {},  # served by Martin
            "fonts": {},  # served by Martin
            "styles": styles,
            "settings": {"rendering": False},
        }


class MapCatalogController(ApiController):
    """The light layer index — metadata only, never style blobs."""

    @modify(
        operation_id="map-catalog",
        headers=cache_headers(CACHE_MAX_AGE),
    )
    def get(
        self,
        parsed_query: Query[MapCatalogQuery],
    ) -> MapCatalogResponse:
        """Map layer catalog (overlays and basemaps).

        Metadata index for map clients: identities, labels in the
        request language, icons, parameter schemas, device-tier
        variants, category projections and coverage bounds. Large
        styles are referenced by URL, small ones inlined.
        """
        queryset = MapLayer.objects.filter(is_active=True).select_related(
            "slot", "coverage", "license", "fallback"
        )
        if parsed_query.role:
            queryset = queryset.filter(role=parsed_query.role)

        with override(parsed_query.lang):
            layers = _build_layer_summaries(queryset)
            slots = [
                {
                    "slug": slot.slug,
                    "label": slot.label_i18n or slot.label,  # noqa: WPS308
                    "order": slot.order,
                }
                for slot in MapSlot.objects.all()
            ]
        return MapCatalogResponse(slots=slots, layers=layers)


def _build_layer_summaries(queryset) -> list[LayerSummary]:
    """Assemble catalog entries grouped by slug (variants merged)."""
    summaries: dict[str, LayerSummary] = {}
    for layer in queryset.prefetch_related(
        "layer_parameters__parameter",
        "layer_categories__category",
        "layer_attributions__organization",
        "legend__sections__items",
        "legend__legend_links__link",
    ):
        summary = summaries.get(layer.slug)
        if summary is None:
            summary = _build_summary(layer)
            summaries[layer.slug] = summary
        summary.variants.append(_build_variant(layer))
    return sorted(summaries.values(), key=lambda s: (s.role, s.order, s.slug))


def _build_summary(layer: MapLayer) -> LayerSummary:
    """One layer's shared metadata (from its first variant)."""
    coverage_bbox = None
    if layer.coverage and layer.coverage.bbox:
        coverage_bbox = list(layer.coverage.bbox)

    parameters = [
        ParameterSummary(
            slug=link.parameter.slug,
            kind=link.parameter.kind,
            label=link.parameter.label_i18n,  # noqa: WPS308
            description=link.parameter.description_i18n,  # noqa: WPS308
            default=link.default_override
            if link.default_override is not None
            else link.parameter.default,
            constraints=link.parameter.constraints,
        )
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

    return LayerSummary(
        slug=layer.slug,
        legend=_legend_payload(layer),
        version=layer.modified.isoformat(),
        role=layer.role,
        name=layer.name_i18n or layer.name,  # noqa: WPS308
        description=layer.description_i18n or layer.description,  # noqa: WPS308
        icon=layer.icon,
        icon_badge=layer.icon_badge,
        slot=layer.slot.slug if layer.slot else None,
        order=layer.order,
        show=layer.show,
        is_default=layer.is_default,
        min_zoom=layer.min_zoom,
        max_zoom=layer.max_zoom,
        coverage_bbox=coverage_bbox,
        fallback_min_zoom=layer.fallback_min_zoom,
        fallback=layer.fallback.slug if layer.fallback else None,
        anchors=layer.anchors,
        preview_url=layer.preview_url,
        config=layer.config,
        interaction=layer.interaction,
        parameters=parameters,
        categories=categories,
        attributions=attributions,
        license=license_payload,
        variants=[],
    )


def _legend_payload(layer: MapLayer) -> dict[str, Any] | None:
    """Serialize the slug-level legend (frontend-compatible shape).

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
        if section.category_id and section.category is not None:
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


def _build_variant(layer: MapLayer) -> LayerVariant:
    """One spec variant: inline small styles, reference big ones."""
    variant = LayerVariant(spec=layer.spec)
    if layer.style is not None:
        encoded = len(json.dumps(layer.style, default=str))
        if encoded <= INLINE_STYLE_MAX_BYTES:
            variant.inline_style = layer.style
        else:
            variant.style_url = style_endpoint_url(layer.slug, layer.spec)
    else:
        # Externally authored: resolve env tokens server-side (API keys
        # live in backend config and never reach the client as params).
        variant.style_url = substitute_env(layer.style_url or "")
    return variant


def _category_projection(category, use: str, order: int) -> dict[str, Any]:
    """Minimal stable category projection (spec D6 — no full DTO).

    Children included so level-aware legends/filters render without a
    second request. Symbol/color fields come straight from the row;
    media URL modes stay a categories-endpoint concern.
    """
    projection: dict[str, Any] = {
        "slug": category.slug,
        "identifier": category.identifier,
        "name": category.name_i18n,  # noqa: WPS308
        "color": category.color,
        "use": use,
        "order": order,
        "children": [],
    }
    for child in category.children.filter(is_active=True):
        projection["children"].append(
            {
                "slug": child.slug,
                "identifier": child.identifier,
                "name": child.name_i18n,  # noqa: WPS308
                "color": child.color,
            }
        )
    return projection


# ── Style endpoint (plain view, hidden from the OpenAPI schema) ┐
#                                                                  ┘


def get_map_style(request: HttpRequest, slug: str) -> HttpResponse:
    """Serve a layer style — resolved by default, tokenized opt-in.

    ``?spec=`` picks the device-tier variant (exact → nearest → single
    — a low-tier request with only a ``high`` variant serves it, and
    vice versa); the response reports the served spec. ``?v=`` is a
    free-form cache buster the client ties to ``updated_at``.
    """
    variants = MapLayer.objects.filter(slug=slug)
    layer = MapLayer.pick_variant(variants, request.GET.get("spec"))
    if layer is None:
        return _style_error(
            f"No active map layer with slug {slug!r}.", HTTPStatus.NOT_FOUND
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
        response.headers["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE}"
        return response

    cached = _style_cache_get(layer, tokenized)
    if cached is not None:
        body, etag = cached
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
        else:
            response = HttpResponse(body, content_type="application/json")
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE}"
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
    if not tokenized:
        payload = _inject_serving_metadata(payload, layer)

    body = json.dumps(payload, separators=(",", ":"))
    etag_source = "|".join(
        (
            slug,
            layer.spec,
            "tokenized" if tokenized else "resolved",
            str(layer.modified),
            str(len(body)),
        )
    )
    etag = f'"{hashlib.sha256(etag_source.encode()).hexdigest()}"'

    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=HTTPStatus.NOT_MODIFIED)
    else:
        response = HttpResponse(body, content_type="application/json")
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE}"
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


def _style_cache_key(layer: MapLayer, tokenized: bool) -> str:
    """Render cache key — version-bumped by ``modified`` automatically."""
    return (
        f"basemaps:style:{layer.pk}:{layer.spec}:"
        f"{'tokenized' if tokenized else 'resolved'}:"
        f"{layer.modified.isoformat()}"
    )


def _style_cache_get(layer: MapLayer, tokenized: bool) -> tuple[str, str] | None:
    from django.core.cache import cache

    return cache.get(_style_cache_key(layer, tokenized))


def _style_cache_set(layer: MapLayer, tokenized: bool, body: str, etag: str) -> None:
    from django.core.cache import cache

    # No TTL: the key embeds ``modified`` — any style/parameter edit
    # changes the key and the old entry falls out naturally.
    cache.set(_style_cache_key(layer, tokenized), (body, etag), timeout=None)


def _style_error(detail: str, status: HTTPStatus) -> HttpResponse:
    """Error body in the project-wide API shape."""
    from django.http import JsonResponse

    return JsonResponse(
        {"code": ErrorCode.not_found, "detail": detail},
        status=status,
    )


paths: list[Any] = [
    path(
        "styles",
        cache_page(CACHE_MAX_AGE)(MapStylesController.as_view()),
        name="map-styles-index",
    ),
    path(
        "config",
        cache_page(CACHE_MAX_AGE)(MapCatalogController.as_view()),
        name="map-catalog",
    ),
    external_path(
        "styles/<slug>.json",
        get_map_style,
        openapi=None,
        name="map-style",
    ),
]
