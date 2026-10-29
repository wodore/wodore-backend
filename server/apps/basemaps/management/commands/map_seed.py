"""Idempotent seed for the map layer catalog (``basemap_seed`` pattern).

Provisions slots, parameters, attribution organizations, the CH
coverage, and every layer the frontend hardcodes today (helpers in
``seed_lib``; big authored basemap styles from ``fixtures/styles/``).
Re-running updates changed fields and reports; it never deletes
rows a curator added on top.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, override

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from server.apps.basemaps import seed_lib as lib
from server.apps.basemaps.models import (
    MapCoverage,
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
from server.apps.basemaps.validation import (
    SUBSET_REVISION,
    run_styl,
    validate_subset_style,
)
from server.apps.external_links.models import ExternalLink
from server.apps.organizations.models import Organization

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "styles"

#: The @maplibre/maplibre-gl-style-spec release the CI styl validation
#: targets (``.github/workflows/test.yml`` — map-style-spec job) — the
#: rules ``version`` recorded on ``full`` inline rows. Subset rows carry
#: ``SUBSET_REVISION`` from ``basemaps.validation`` instead.
STYLE_SPEC_VERSION = "26.4.4"

#: External-derived styles (vendored upstream documents) skip styl
#: wholesale via ``styl_ignored_rules: ["*"]`` — one row-level
#: mechanism that eventually replaces the CI workflow's EXTERNAL_DERIVED
#: skip list (kept for now as defense in depth; same slugs, see
#: ``.github/workflows/test.yml``).

SLOTS = [
    {"slug": "background", "label": "Background (area overlays)", "order": 0},
    {"slug": "ways", "label": "Ways (line/symbol overlays)", "order": 1},
]

PARAMETERS: list[dict[str, Any]] = [
    {
        "slug": "huts.icon_scale",
        "kind": MapParameter.Kind.number,
        "label": "Hut icon size",
        "description": "Scales the hut symbols on the map.",
        "default": 1,
        "constraints": {"min": 0.5, "max": 2, "step": 0.1},
    },
    {
        "slug": "date",
        "kind": MapParameter.Kind.date,
        "label": "Availability date",
        "description": (
            "The date the availability overlay fetches data for "
            "(runtime; managed by the client)."
        ),
        "default": None,
        "constraints": None,
    },
]

ORGS = [
    {
        "slug": "swisstopo",
        "name": "swisstopo",
        "attribution": "swisstopo",
        "url": "https://www.swisstopo.admin.ch",
    },
    {
        "slug": "bafu",
        "name": "BAFU",
        "attribution": "BAFU",
        "url": "https://www.bafu.admin.ch",
    },
    {
        "slug": "openstreetmap",
        "name": "OpenStreetMap",
        "attribution": "© OpenStreetMap contributors",
        "url": "https://www.openstreetmap.org/copyright",
    },
    {
        "slug": "waymarkedtrails",
        "name": "Waymarked Trails",
        "attribution": "Waymarked Trails",
        "url": "https://hiking.waymarkedtrails.org",
    },
    {
        "slug": "maptoolkit",
        "name": "Maptoolkit",
        "attribution": "Maptoolkit",
        "url": "https://www.maptoolkit.net",
    },
    {
        "slug": "openfreemap",
        "name": "OpenFreeMap",
        "attribution": "OpenFreeMap",
        "url": "https://openfreemap.org",
    },
    {
        "slug": "maptiler",
        "name": "MapTiler",
        "attribution": "MapTiler",
        "url": "https://www.maptiler.com",
    },
    {
        "slug": "mapy",
        "name": "mapy.com",
        "attribution": "© Seznam.cz, a.s.",
        "url": "https://mapy.com",
    },
    {
        "slug": "bav",
        "name": "BAV",
        "attribution": "Bundesamt für Verkehr (BAV)",
        "url": "https://www.bav.admin.ch",
    },
    {
        "slug": "transitland",
        "name": "Transitland",
        "attribution": "Transitland · © OpenStreetMap contributors",
        "url": "https://www.transit.land",
    },
]

# CH + border strips (frontend ch-swisstopo-full bbox parity)
CH_BBOX = (5.7, 45.6, 10.9, 48.1)

# Legends per layer slug — category-driven sections or static items
# (colors/widths may hold {{parameter}} tokens). Links reuse
# external_links.ExternalLink rows (get-or-create by URL).
LEGENDS: dict[str, dict[str, Any]] = {
    "huts": {
        "sections": [
            {
                "title": "Accommodation",
                "description": "Hut types by symbol.",
                "type": "symbol_dual",
                "category": "accommodation",
            },
            {
                "title": "Availability",
                "description": "Occupancy status per day.",
                "type": "symbol_detailed",
                "category": "availability",
            },
        ]
    },
    "transport-stops": {
        "sections": [
            {
                "title": "Transport stops",
                "description": "Stops by transit mode (Transitland).",
                "type": "symbol_mono",
                "category": "transport",
            }
        ],
        "links": [
            {
                "name": "Transitland",
                "url": "https://www.transit.land",
            },
            {
                "name": "GTFS route types",
                "url": "https://gtfs.org/documentation/schedule/reference/#routetype",
            },
        ],
    },
    "ch.swisstopo.swisstlm3d-wanderwege": {
        "sections": [
            {
                "title": "Hiking trails",
                "description": "Trail categories by difficulty.",
                "type": "line",
                "items": [
                    {"label": "Wanderweg", "color": "#fdc200"},
                    {"label": "Bergwanderweg", "color": "#ff0000"},
                    {"label": "Alpinwanderweg", "color": "#0000ff"},
                ],
            }
        ],
        "links": [
            {
                "name": "Wanderland Schweiz",
                "url": "https://www.schweizmobil.ch/de/wanderland.html",
            },
            {
                "name": "SAC scale",
                "url": "https://www.sac-cas.ch/de/huetten-und-touren/sac-tourenportal/schwierigkeitsskala/",
            },
        ],
    },
    "slopes": {
        "sections": [
            {
                "title": "Difficulty",
                "type": "line",
                "items": [
                    {"label": "Green", "color": "#4CAF50"},
                    {"label": "Blue", "color": "#2196F3"},
                    {"label": "Red", "color": "#F44336"},
                    {"label": "Black", "color": "#212121"},
                ],
            }
        ]
    },
    "ch.swisstopo.hangneigung-ueber_30": {
        "sections": [
            {
                "title": "Slope angle",
                "type": "area",
                "items": [
                    {"label": "30° - 35°", "color": "#f2e50a"},
                    {"label": "35° - 40°", "color": "#f46f24"},
                    {"label": "40° - 45°", "color": "#de055b"},
                    {"label": "> 45°", "color": "#c889bb"},
                ],
            }
        ],
        "links": [
            {
                "name": "Avalanche bulletin",
                "url": "https://www.slf.ch/de/lawinenbulletin-und-schneesituation.html",
            },
        ],
    },
    "wildruhe_und_jagdbann": {
        "sections": [
            {
                "title": "Protected areas",
                "type": "area",
                "items": [
                    {"label": "By law", "color": "#ff9b8d"},
                    {"label": "Recommended", "color": "#ffed80"},
                ],
            }
        ],
    },
    "ch.bafu.alpweiden-herdenschutzhunde": {
        "sections": [
            {
                "title": "Guard dog zones",
                "type": "area",
                "items": [{"label": "Pastures", "color": "#ffb300"}],
            }
        ],
    },
    "ch.swisstopo-karto.skitouren": {
        "links": [
            {
                "name": "Skitourenkarte",
                "url": "https://www.swisstopo.admin.ch/de/karten-daten-online/karten-geodaten/freizeitkarten/skitourenkarte.html",
            },
            {
                "name": "Avalanche bulletin",
                "url": "https://www.slf.ch/de/lawinenbulletin-und-schneesituation.html",
            },
        ]
    },
    "ch.swisstopo.schneeschuhwandern": {
        "links": [
            {
                "name": "Snowshoe trails",
                "url": "https://www.swisstopo.admin.ch/de/karten-daten-online/karten-geodaten/freizeitkarten/schneeschuhwandern.html",
            },
        ]
    },
    "mtb": {
        "links": [
            {
                "name": "Mountainbikeland",
                "url": "https://www.schweizmobil.ch/de/mountainbikeland.html",
            },
        ]
    },
    "cycling": {
        "links": [
            {"name": "Veloland", "url": "https://www.schweizmobil.ch/de/veloland.html"},
        ]
    },
}


def _opacity_param(
    slug: str, label: str, zoom_out: float, zoom_main: float, zoom_in: float
) -> dict[str, Any]:
    return {
        "slug": slug,
        "kind": MapParameter.Kind.opacity_curve,
        "label": label,
        "description": "Zoom-dependent opacity of this overlay.",
        "default": lib.opacity_levels(zoom_out, zoom_main, zoom_in),
        "constraints": {"max_stops": 12},
    }


PARAMETERS += [
    _opacity_param("hiking.opacity", "Hiking trails opacity", 0.4, 0.9, 0.7),
    _opacity_param("mtb.opacity", "MTB routes opacity", 0.6, 0.9, 0.7),
    _opacity_param("cycling.opacity", "Cycling routes opacity", 0.6, 0.9, 0.7),
    _opacity_param("slopes.opacity", "Ski slopes opacity", 0.3, 0.6, 0.3),
    _opacity_param("skitouren.opacity", "Skitour routes opacity", 0.0, 0.8, 0.3),
    _opacity_param("snowshoes.opacity", "Snowshoe routes opacity", 0.0, 0.8, 0.3),
    _opacity_param("hillslope.opacity", "Slope shading opacity", 0.1, 0.2, 0.4),
    _opacity_param("nature.opacity", "Protected areas opacity", 0.7, 0.5, 0.3),
    _opacity_param(
        "sheepdogs.opacity", "Livestock guard dog zones opacity", 0.7, 0.5, 0.3
    ),
]


def _fixture_style(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _links_legend(
    title: str, description: str, links: list[dict[str, str]]
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    return {
        "sections": [{"title": title, "description": description, "items": items}],
        "links": links,
    }


LAYERS: list[dict[str, Any]] = [
    # ── Overlays ──────────────────────────────────────────────────────
    {
        "slug": "huts",
        "role": MapLayer.Role.overlay,
        "name": "Huts",
        "description": (
            "Mountain huts and bivouacs with type symbols and bed "
            "availability per day (one overlay, both sources — frontend "
            "hutsStyle parity)."
        ),
        "icon": "huts",
        "slot": "ways",
        "order": 0,
        "min_zoom": 5,
        "style": lib.HUTS_STYLE,
        "parameters": {"huts.icon_scale": None, "date": None},
        "variants": [
            # Subset twin for the Leaflet fallback (menu-toggleable there
            # instead of the fallback's own always-on rendering): the
            # availability disc (wd-huts-occupation) plus a trimmed
            # wd-huts symbol — the day-strip columns and the
            # feature-state selection circle are outside subset v0.1
            # (see seed_lib._huts_style_subset for the layer-by-layer
            # rationale). config (filters + clustering) is slug-level and
            # rides both rows; parameters sync per row, so the {{date}}
            # token in the wd-bookings tiles stays resolvable.
            {
                "profile": MapLayer.Profile.subset,
                "version": SUBSET_REVISION,
                "style": lib.HUTS_STYLE_SUBSET,
                # Variant parameters REPLACE the parent list (see
                # _seed_layer): the twin drops the inert icon-scale slider
                # (its baked icon-size ladder never reads the token) but
                # keeps {{date}} for the wd-bookings tile template.
                "parameters": {"date": None},
            }
        ],
        "attributions": [],
        "categories": [
            {"slug": "accommodation", "use": "filter"},
            {"slug": "accommodation", "use": "legend"},
            {"slug": "availability", "use": "legend"},
        ],
        "config": {
            "filters": [
                {
                    "id": "hutTypes",
                    "label": "Accommodation types",
                    "type": "multi-select",
                    "category": "accommodation",
                    "defaultValue": [],
                    "mapLayers": [
                        "wd-huts",
                        "wd-huts-selected",
                        "wd-huts-occupation",
                        "wd-huts-occupation-day0",
                        "wd-huts-occupation-day1",
                        "wd-huts-occupation-day2",
                        "wd-huts-occupation-day3",
                    ],
                    "mapProperty": "type_standard_identifier",
                    "filterExpression": "in",
                }
            ],
            # Clustering rendering hint (style-profiles-subset D5): never
            # inside the style document (MapLibre allows ``cluster`` only
            # on geojson sources) — one config serves client-side
            # clustering today and precomputed DB clusters later. Features
            # lacking ``groupByProperty`` form one null bucket.
            "clustering": {
                "enabled": True,
                "source": "wd-huts",
                "groupByProperty": "type_standard_slug",
                "radius": 48,
                "maxZoom": 10,
                "bubble": {
                    "colorProperty": "type_standard_color",
                    "iconProperty": "type_standard_identifier",
                    "countProperty": "point_count",
                },
            },
        },
        "interaction": {
            "click": {"layers": ["wd-huts"], "behavior": "hut-detail", "min_zoom": 8}
        },
    },
    {
        "slug": "transport-stops",
        "role": MapLayer.Role.overlay,
        "name": "Public transport stops",
        "description": (
            "Train, bus, tram, metro and ferry stops (Transitland vector "
            "tiles, served as MLT through Martin)."
        ),
        "icon": "transport",
        "slot": "ways",
        "order": 2,
        "min_zoom": 5,
        "style": lib.TRANSPORT_STYLE,
        "variants": [
            # Subset twin for the Leaflet fallback (no-WebGL map): the
            # same vector document minus promoteId and the default
            # layout.visibility — no clustering anymore (vector tiles
            # sample server-side below z12; the old client-side
            # clustering existed because the BAV geojson was one blob).
            {
                "profile": MapLayer.Profile.subset,
                "version": SUBSET_REVISION,
                "style": lib.TRANSPORT_STYLE_SUBSET,
            }
        ],
        "attributions": ["transitland", "openstreetmap"],
        "categories": [
            {"slug": "transport", "use": "filter"},
            {"slug": "transport", "use": "legend"},
        ],
        "config": {
            "filters": [
                {
                    "id": "transportTypes",
                    "label": "Transit modes",
                    "type": "multi-select",
                    "category": "transport",
                    "defaultValue": [],
                    "mapLayers": ["transport-stops"],
                    # route_types_basic is Transitland's JSON-string array
                    # ("[2, 3]" — basic GTFS types); option values are the
                    # category identifiers. PRESENCE semantics: a stop
                    # matches a mode when the array contains it — the
                    # frontend's generic filter applies exact membership
                    # on the whole property value, so this needs its
                    # presence mode (`filterExpression: in`, currently
                    # ignored by applyFilter) — frontend follow-up, the
                    # catalog data is final.
                    "mapProperty": "route_types_basic",
                    "filterExpression": "in",
                }
            ]
        },
    },
    {
        "slug": "ch.swisstopo.swisstlm3d-wanderwege",
        "role": MapLayer.Role.overlay,
        "name": "Hiking trails",
        "description": "Swiss hiking trail network (swisstopo).",
        "icon": "hiking",
        "icon_badge": "ch",
        "slot": "ways",
        "order": 3,
        "style": lib.swisstopo_overlay_style(
            "ch.swisstopo.swisstlm3d-wanderwege",
            "ch.swisstopo.swisstlm3d-wanderwege",
            opacity_token="hiking.opacity",
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"hiking.opacity": None},
        "attributions": ["swisstopo"],
        "config": _links_legend(
            "Hiking trails",
            "Trail categories by difficulty.",
            [
                {
                    "name": "Wanderland Schweiz",
                    "url": "https://www.schweizmobil.ch/de/wanderland.html",
                },
                {
                    "name": "SAC scale",
                    "url": "https://www.sac-cas.ch/de/huetten-und-touren/sac-tourenportal/schwierigkeitsskala/",
                },
            ],
        ),
    },
    {
        "slug": "mtb",
        "role": MapLayer.Role.overlay,
        "name": "Mountain bike routes",
        "description": "MTB routes (Waymarked Trails).",
        "icon": "mtb",
        "slot": "ways",
        "order": 4,
        "style": lib.raster_style(
            "mtb", lib.waymarkedtrails_urls("mtb"), opacity_token="mtb.opacity"
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"mtb.opacity": None},
        "attributions": ["openstreetmap", "waymarkedtrails"],
    },
    {
        "slug": "cycling",
        "role": MapLayer.Role.overlay,
        "name": "Cycling routes",
        "description": "Cycling routes (Waymarked Trails).",
        "icon": "cycling",
        "slot": "ways",
        "order": 5,
        "style": lib.raster_style(
            "cycling",
            lib.waymarkedtrails_urls("cycling"),
            opacity_token="cycling.opacity",
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"cycling.opacity": None},
        "attributions": ["openstreetmap", "waymarkedtrails"],
    },
    {
        "slug": "slopes",
        "role": MapLayer.Role.overlay,
        "name": "Ski slopes",
        "description": "Ski slopes by difficulty (Waymarked Trails).",
        "icon": "skislopes",
        "slot": "ways",
        "order": 6,
        "min_zoom": 8,
        "style": lib.raster_style(
            "slopes",
            lib.waymarkedtrails_urls("slopes"),
            min_zoom=8,
            opacity_token="slopes.opacity",
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"slopes.opacity": None},
        "attributions": ["openstreetmap", "waymarkedtrails"],
    },
    {
        "slug": "ch.swisstopo-karto.skitouren",
        "role": MapLayer.Role.overlay,
        "name": "Skitour routes",
        "description": "Skitour routes (swisstopo skitourenkarte).",
        "icon": "skitouren",
        "icon_badge": "ch",
        "slot": "ways",
        "order": 7,
        "min_zoom": 8,
        "style": lib.swisstopo_overlay_style(
            "ch.swisstopo-karto.skitouren",
            "ch.swisstopo-karto.skitouren",
            opacity_token="skitouren.opacity",
            min_zoom=8,
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"skitouren.opacity": None},
        "attributions": ["swisstopo"],
    },
    {
        "slug": "ch.swisstopo.schneeschuhwandern",
        "role": MapLayer.Role.overlay,
        "name": "Snowshoe routes",
        "description": "Snowshoe trails (swisstopo).",
        "icon": "snowshoeing",
        "icon_badge": "ch",
        "slot": "ways",
        "order": 8,
        "min_zoom": 8,
        "style": lib.swisstopo_overlay_style(
            "ch.swisstopo.schneeschuhwandern",
            "ch.swisstopo.schneeschuhwandern",
            opacity_token="snowshoes.opacity",
            min_zoom=8,
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"snowshoes.opacity": None},
        "attributions": ["swisstopo"],
    },
    {
        "slug": "ch.swisstopo.hangneigung-ueber_30",
        "role": MapLayer.Role.overlay,
        "name": "Steep slopes (30°+)",
        "description": "Slope angles above 30° (swisstopo).",
        "icon": "hillslopes",
        "icon_badge": "ch",
        "slot": "background",
        "order": 9,
        "min_zoom": 10,
        "style": lib.swisstopo_overlay_style(
            "ch.swisstopo.hangneigung-ueber_30",
            "ch.swisstopo.hangneigung-ueber_30",
            opacity_token="hillslope.opacity",
            min_zoom=10,
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"hillslope.opacity": None},
        "attributions": ["swisstopo"],
    },
    {
        "slug": "wildruhe_und_jagdbann",
        "role": MapLayer.Role.overlay,
        "name": "Protected nature areas",
        "description": "Wildlife reserves and hunting bans (BAFU).",
        "icon": "deer2",
        "icon_badge": "ch",
        "slot": "background",
        "order": 10,
        "style": lib.swisstopo_overlay_style(
            "wildruhe_und_jagdbann",
            [
                "ch.bafu.wrz-wildruhezonen_portal",
                "ch.bafu.wrz-jagdbanngebiete_select",
            ],
            opacity_token="nature.opacity",
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"nature.opacity": None},
        "attributions": ["bafu", "swisstopo"],
    },
    {
        "slug": "ch.bafu.alpweiden-herdenschutzhunde",
        "role": MapLayer.Role.overlay,
        "name": "Livestock guard dogs",
        "description": "Pastures with livestock guard dogs (BAFU).",
        "icon": "dog",
        "icon_badge": "ch",
        "slot": "background",
        "order": 11,
        "style": lib.swisstopo_overlay_style(
            "ch.bafu.alpweiden-herdenschutzhunde",
            "ch.bafu.alpweiden-herdenschutzhunde",
            opacity_token="sheepdogs.opacity",
        ),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "parameters": {"sheepdogs.opacity": None},
        "attributions": ["bafu", "swisstopo"],
    },
    # ── Basemaps ──────────────────────────────────────────────────────
    # Picker visibility (frontend parity): only product basemaps carry
    # show=True — internal variants (hill A/B, upstream reference) and
    # automatic fallbacks stay hidden but active (fallback chains and
    # saved selections keep resolving). Order drives the picker sort.
    {
        "slug": "wd-outdoor-base-mtk-hill",
        "role": MapLayer.Role.basemap,
        "name": "Wodore Outdoor",
        "description": (
            "Outdoor basemap with client-side raster-dem relief "
            "(higher-res in CH; heavier on the GPU)."
        ),
        "spec": MapLayer.Spec.high,
        "is_default": True,  # the frontend's default basemap (PR #292 seed)
        "order": 0,  # the product slot (plain non-hill pair retired)
        "show": True,
        "style": _fixture_style("wd-outdoor-base-mtk-hill"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["maptoolkit"],
    },
    {
        # A/B pair of the product basemap: identical style except the
        # hillshading — martin server-baked raster (AWS normals) instead
        # of the client GPU hillshade. Hidden from the picker (show=False)
        # but active: mapcompare + fallback chains resolve it. Re-added
        # for the hillshade A/B decision (PR #375 lane).
        "slug": "wd-outdoor-base-mtk",
        "role": MapLayer.Role.basemap,
        "name": "Wodore Outdoor (server relief)",
        "description": (
            "Outdoor basemap with the martin server-baked hillshade "
            "(lighter on the client, coarser source DEM)."
        ),
        "spec": MapLayer.Spec.high,
        "order": 1,
        "show": False,  # A/B variant — not a picker product
        "style": _fixture_style("wd-outdoor-base-mtk"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["maptoolkit"],
    },
    {
        "slug": "wd-outdoor-base-ofm-hill",
        "role": MapLayer.Role.basemap,
        "name": "Wodore Outdoor (OpenFreeMap, client relief)",
        "description": "OpenFreeMap fallback with the original client hillshade.",
        "spec": MapLayer.Spec.high,
        "order": 7,
        "show": False,  # A/B variant of the hidden fallback
        "style": _fixture_style("wd-outdoor-base-ofm-hill"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["openfreemap"],
    },
    {
        "slug": "mtk-outdoor",
        "role": MapLayer.Role.basemap,
        "name": "Maptoolkit Outdoor (upstream)",
        "description": (
            "Original upstream Maptoolkit outdoor style with client-side "
            "relief (raster-dem + bathymetry + AO passes)."
        ),
        "spec": MapLayer.Spec.high,
        "order": 8,
        "show": False,  # upstream visual reference, not shipped
        "style": _fixture_style("mtk-outdoor"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["maptoolkit"],
    },
    {
        "slug": "world-topo",
        "role": MapLayer.Role.basemap,
        "name": "World Topo",
        "description": "Worldwide topo raster (mapproxy world_topo facade, caps at z16).",
        "spec": MapLayer.Spec.high,
        "order": 1,
        "style": _fixture_style("world-topo"),
        "profile": MapLayer.Profile.subset,
        "version": SUBSET_REVISION,
        "attributions": ["openstreetmap"],
    },
    {
        "slug": "world-satellite-hybrid",
        "role": MapLayer.Role.basemap,
        "name": "Satellite (hybrid)",
        "description": (
            "Aerial imagery with street/place overlay (mapproxy "
            "world_satellite + OpenFreeMap vector)."
        ),
        "spec": MapLayer.Spec.high,
        "order": 2,
        "style": _fixture_style("world-satellite-hybrid"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["openstreetmap", "openfreemap"],
    },
    {
        "slug": "ch-swisstopo-light",
        "role": MapLayer.Role.basemap,
        "name": "Swiss light basemap",
        "description": "swisstopo vector light basemap.",
        "spec": MapLayer.Spec.high,
        "order": 9,
        "show": False,  # replaced by wd-outdoor-base-mtk as THE vector map
        "style_url": (
            "https://vectortiles.geo.admin.ch/styles/"
            "ch.swisstopo.lightbasemap.vt/style.json"
        ),
        "anchors": {
            "ways": {"before": "Other place labels"},
            "background": {"before": "Building line"},
        },
        "variants": [
            {
                "spec": MapLayer.Spec.low,
                "style": lib.osm_raster_style(),
                "styl_ignored_rules": ["*"],  # external-derived (variant-level)
            }
        ],
        "attributions": ["swisstopo", "openstreetmap"],
    },
    {
        "slug": "ch-swisstopo-full",
        "role": MapLayer.Role.basemap,
        "name": "Swiss raster map",
        "description": "swisstopo pixelkarte (CH coverage).",
        "spec": MapLayer.Spec.medium,
        "order": 3,
        "show": False,  # owner call 2026-10-16: picker ships the top-3 only
        "coverage": "ch",
        "fallback_min_zoom": 7,
        "style": lib.swisstopo_pixelkarte_style(),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["swisstopo"],
    },
    {
        "slug": "maptiler-hybrid",
        "role": MapLayer.Role.basemap,
        "name": "Satellite hybrid",
        "description": "MapTiler satellite hybrid.",
        "spec": MapLayer.Spec.high,
        "order": 4,
        "show": False,  # owner call 2026-10-16: picker ships the top-3 only
        "style_url": (
            "https://api.maptiler.com/maps/hybrid/style.json"
            "?key={{env:WODORE_MAPTILER_API_KEY}}"
        ),
        "anchors": {
            "ways": {"before": "Tunnel"},
            "background": {"before": "State labels"},
        },
        "attributions": ["maptiler"],
    },
    {
        "slug": "openfreemap-liberty",
        "role": MapLayer.Role.basemap,
        "name": "OpenFreeMap liberty",
        "description": "Keyless OpenFreeMap liberty style.",
        "spec": MapLayer.Spec.high,
        "order": 10,
        "show": False,  # automatic keyless fallback, not a product entry
        "style_url": "https://tiles.openfreemap.org/styles/liberty",
        "attributions": ["openfreemap"],
    },
    {
        "slug": "mapy-outdoor",
        "role": MapLayer.Role.basemap,
        "name": "Mapy.com outdoor (reference)",
        "description": (
            "Seznam tourist map — keyless compare reference for the outdoor "
            "cartography; needs MAPY_COM_API_KEY (free tier: 250k tiles/month)."
        ),
        "spec": MapLayer.Spec.high,
        "order": 11,
        "show": False,  # reference/compare entry, not a product basemap
        "style": _fixture_style("mapy-outdoor"),
        "styl_ignored_rules": ["*"],  # external-derived: styl skips wholesale
        "attributions": ["mapy"],
    },
]


#: Env-registry entries the map catalog references (``envvars.EnvVar``).
#: Seeded only when missing — re-runs never touch values an operator set
#: in the admin (get_or_create semantics).
ENV_REGISTRY_ENTRIES: list[dict[str, str]] = [
    {
        "name": "WODORE_MAPTILER_API_KEY",
        "description": (
            "MapTiler hybrid satellite basemap (maptiler-hybrid layer style URL)"
        ),
    },
    {
        "name": "MAPY_COM_API_KEY",
        "description": "Mapy.com outdoor reference basemap (mapy-outdoor layer)",
    },
    {
        "name": "TRANSITLAND_API_KEY",
        "description": (
            "Transitland v2 vector tiles API key — the transport-stops "
            "overlay's Martin passthrough upstream auth (server-side "
            "apikey header; never appears in a client-visible URL)"
        ),
    },
]


class Command(BaseCommand):
    """Provision the map layer catalog (idempotent)."""

    help = "Seed map slots, parameters, layers and links (frontend parity)."

    @override
    def handle(self, *args: Any, **options: Any) -> None:
        created = updated = 0

        slots = self._seed_slots()
        params = self._seed_parameters()
        orgs = self._seed_orgs()
        coverage = self._seed_coverage()
        self._seed_env_registry()

        self._retire_merged_layers()

        # transport-stops paint follows the live `transport` category
        # tree (the legend/filter resolve from the same rows) — rebuild
        # the two style documents with the DB colors before seeding.
        self._apply_transport_palette()

        for definition in LAYERS:
            variants = [definition] + definition.get("variants", [])
            for variant in variants:
                result = self._seed_layer(
                    variant, definition, slots, params, orgs, coverage
                )
                created += result[0]
                updated += result[1]

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {created} created, {updated} updated, "
                f"{MapLayer.objects.count()} layer rows total."
            )
        )

    # ── Steps ──────────────────────────────────────────────────────────

    def _seed_env_registry(self) -> None:
        """Ensure the env-registry rows the catalog references exist.

        ``get_or_create`` only — an operator's value / is_active /
        env_fallback settings are never overwritten on re-runs.
        """
        from server.apps.envvars.models import EnvVar

        for entry in ENV_REGISTRY_ENTRIES:
            _, was_created = EnvVar.objects.get_or_create(
                name=entry["name"],
                defaults={
                    "value": "",
                    "env_fallback": True,
                    "is_active": True,
                    "description": entry["description"],
                },
            )
            if was_created:
                self.stdout.write(f"Env registry entry created: {entry['name']}")

    def _retire_merged_layers(self) -> None:
        """Drop layers merged into another seed definition.

        ``huts-availability`` was folded into ``huts`` (one overlay, both
        sources). Seed rows for retired slugs are deleted explicitly —
        the seed never deletes *curator-added* rows, only its own former
        identities. The slug-level legend goes with the layer (kept only
        when another layer still references it).
        """
        retired = ("huts-availability",)
        layers = MapLayer.objects.filter(slug__in=retired)
        legend_ids = set(
            layers.exclude(legend=None).values_list("legend_id", flat=True)
        )
        deleted, _ = layers.delete()
        if deleted:
            self.stdout.write(
                f"  Removed merged layer rows: {deleted} ({', '.join(retired)})"
            )
            # Legends orphaned by the merge (no layer references them anymore)
            MapLegend.objects.filter(pk__in=legend_ids, layers__isnull=True).delete()

    def _seed_slots(self) -> dict[str, MapSlot]:
        slots: dict[str, MapSlot] = {}
        for data in SLOTS:
            slot, _ = MapSlot.objects.update_or_create(slug=data["slug"], defaults=data)
            slots[slot.slug] = slot
        return slots

    def _seed_parameters(self) -> dict[str, MapParameter]:
        params: dict[str, MapParameter] = {}
        for data in PARAMETERS:
            param, _ = MapParameter.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "kind": data["kind"],
                    "label": data["label"],
                    "description": data["description"],
                    "default": data["default"],
                    "constraints": data["constraints"],
                },
            )
            params[param.slug] = param
        return params

    def _seed_orgs(self) -> dict[str, Organization]:
        orgs: dict[str, Organization] = {}
        for data in ORGS:
            org, _ = Organization.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"],
                    "attribution": data["attribution"],
                    "url": data["url"],
                },
            )
            orgs[org.slug] = org
        return orgs

    def _seed_coverage(self) -> MapCoverage:
        west, south, east, north = CH_BBOX
        geometry = MultiPolygon(
            Polygon(
                (
                    (west, south),
                    (east, south),
                    (east, north),
                    (west, north),
                    (west, south),
                )
            )
        )
        coverage, _ = MapCoverage.objects.update_or_create(
            slug="ch",
            defaults={
                "name": "Switzerland + border strips",
                "provenance": "Frontend ch-swisstopo-full bbox parity",
                "geometry": geometry,
            },
        )
        return coverage

    def _apply_transport_palette(self) -> None:
        """Rebuild the transport-stops styles from the live category rows.

        The legend is category-driven and reads ``transport`` children
        colors at serve time — baking the same colors into the paint at
        seed time keeps map and legend from drifting apart. Missing
        rows (or the model-default green) keep the seed_lib fallback
        palette.
        """
        from server.apps.categories.models import Category

        colors: dict[str, str] = {}
        for slug, _basic in lib.TRANSPORT_MODES:
            category = Category.objects.filter(
                slug=slug, parent__slug="transport", is_active=True
            ).first()
            if category and category.color != "#4B8E43":
                colors[slug] = category.color
        for definition in LAYERS:
            if definition.get("slug") != "transport-stops":
                continue
            definition["style"] = lib.transport_style(colors)
            for variant in definition.get("variants", []):
                if "style" in variant:
                    variant["style"] = lib.transport_style_subset(colors)

    def _seed_layer(
        self,
        variant: dict[str, Any],
        parent: dict[str, Any],
        slots: dict[str, MapSlot],
        params: dict[str, MapParameter],
        orgs: dict[str, Organization],
        coverage: MapCoverage,
    ) -> tuple[int, int]:
        slug = parent["slug"]
        spec = variant.get("spec", MapLayer.Spec.medium)
        profile = variant.get("profile", parent.get("profile", MapLayer.Profile.full))
        # Explicit variants own their style source outright (a low-spec
        # raster variant must not inherit the parent's style_url — the
        # style XOR constraint would fire).
        if "style" in variant or "style_url" in variant:
            style_source = {
                "style": variant.get("style"),
                "style_url": variant.get("style_url"),
            }
        else:
            style_source = {
                "style": parent.get("style"),
                "style_url": parent.get("style_url"),
            }
        # Rules version default: explicit per-entry overrides win;
        # inline rows record the styl-validated style-spec release,
        # external style_url rows stay empty (not our document).
        if "version" in variant or "version" in parent:
            version = variant.get("version", parent.get("version", ""))
        elif style_source["style_url"]:
            version = ""
        else:
            version = STYLE_SPEC_VERSION

        # Seed gating (style-profiles-subset D6): ``update_or_create``
        # bypasses ``clean()`` — the profile-relevant invariants are
        # validated directly, BEFORE the write, so a bad definition
        # fails the seed loudly instead of drifting in via CI sweep
        # only. Token/attribution checks need the M2M syncs below and
        # stay with the sweep (``validate_map_styles``).
        styl_ignored = variant.get(
            "styl_ignored_rules", parent.get("styl_ignored_rules")
        )
        if style_source["style"] is not None:
            if profile == MapLayer.Profile.subset:
                validate_subset_style(style_source["style"])
            if not version:
                msg = f"{slug} [{spec}/{profile}]: inline styles need a rules version"
                raise CommandError(msg)
            # styl: same graceful rules as ``clean()`` — an absent binary
            # skips silently; a present binary's E-codes (minus this
            # row's ignore list) fail the seed loudly.
            styl_result = run_styl(
                style_source["style"], ignored_rules=styl_ignored or ()
            )
            if styl_result is not None and styl_result.errors:
                msg = f"{slug} [{spec}/{profile}]: styl: " + "; ".join(
                    styl_result.errors
                )
                raise CommandError(msg)

        defaults = {
            "role": parent["role"],
            "name": parent["name"],
            "description": parent.get("description", ""),
            "icon": parent.get("icon", ""),
            "icon_badge": variant.get("icon_badge", parent.get("icon_badge", "")),
            "slot": slots.get(parent["slot"]) if parent.get("slot") else None,
            "order": parent.get("order", 0),
            "show": variant.get("show", parent.get("show", True)),
            "is_default": variant.get("is_default", parent.get("is_default", False)),
            "min_zoom": variant.get("min_zoom", parent.get("min_zoom")),
            "max_zoom": variant.get("max_zoom", parent.get("max_zoom")),
            "style": style_source["style"],
            "style_url": style_source["style_url"],
            "profile": profile,
            "version": version,
            "styl_ignored_rules": styl_ignored,
            "config": parent.get("config"),
            "interaction": parent.get("interaction"),
            "coverage": coverage if parent.get("coverage") == "ch" else None,
            "fallback_min_zoom": parent.get("fallback_min_zoom"),
            "anchors": variant.get("anchors", parent.get("anchors")),
            "legend": self._seed_legend(parent["slug"]),
        }

        layer, was_created = MapLayer.objects.update_or_create(
            slug=slug, spec=spec, profile=profile, defaults=defaults
        )
        changed = int(not was_created)  # update_or_create reports nothing finer

        if parent.get("fallback"):
            fallback = MapLayer.objects.filter(slug=parent["fallback"]).first()
            if fallback and layer.fallback != fallback:
                layer.fallback = fallback
                layer.save(update_fields=["fallback"])

        # Parameter precedence: a variant's own ``parameters`` replace
        # the parent's list for that row (the parent list stays the
        # default for variants without one) — subset twins drop inert
        # knobs the trimmed document never references.
        wanted_parameters = variant.get("parameters", parent.get("parameters", {}))
        self._sync_parameters(layer, wanted_parameters, params)
        self._sync_categories(layer, parent)
        self._sync_attributions(layer, parent, orgs)

        return int(was_created), changed

    def _seed_legend(self, slug: str) -> MapLegend | None:
        """Create/update the slug-level legend (shared by all variants)."""
        definition = LEGENDS.get(slug)
        if definition is None:
            existing = MapLayer.objects.filter(slug=slug).first()
            return existing.legend if existing else None

        legend = MapLayer.objects.filter(slug=slug).first()
        legend = (
            legend.legend if legend and legend.legend else MapLegend.objects.create()
        )
        MapLegend.objects.filter(pk=legend.pk).update(
            title=definition.get("title", ""),
            description=definition.get("description", ""),
        )

        wanted_sections = definition.get("sections", [])
        existing_section_ids = set()
        for order, section_def in enumerate(wanted_sections):
            category = None
            if section_def.get("category"):
                from server.apps.categories.models import Category

                category = Category.objects.filter(
                    slug=section_def["category"], parent__isnull=True
                ).first()
            section, _ = MapLegendSection.objects.update_or_create(
                legend=legend,
                order=order,
                defaults={
                    "title": section_def.get("title", ""),
                    "description": section_def.get("description", ""),
                    "type": section_def.get("type", "symbol_detailed"),
                    "category": category,
                },
            )
            existing_section_ids.add(section.pk)
            for item_order, item_def in enumerate(section_def.get("items", [])):
                MapLegendItem.objects.update_or_create(
                    section=section,
                    order=item_order,
                    defaults={
                        "label": item_def.get("label", ""),
                        "description": item_def.get("description", ""),
                        "color": item_def.get("color", ""),
                        "width": item_def.get("width", ""),
                        "icon": item_def.get("icon", ""),
                    },
                )
        # Drop surplus seeded sections beyond the wanted list
        for section in legend.sections.all():
            if section.pk not in existing_section_ids and section.order >= len(
                wanted_sections
            ):
                section.delete()

        for order, link_def in enumerate(definition.get("links", [])):
            link = self._external_link(link_def["name"], link_def["url"])
            MapLegendLink.objects.update_or_create(
                legend=legend, link=link, defaults={"order": order}
            )
        return legend

    @staticmethod
    def _external_link(name: str, url: str) -> ExternalLink:
        """Get-or-create an external link by URL (stable identifier)."""
        import hashlib

        identifier = hashlib.sha256(url.encode()).hexdigest()[:10]
        link, _ = ExternalLink.objects.update_or_create(
            url=url,
            defaults={"identifier": identifier, "label": name},
        )
        return link

    def _sync_parameters(
        self,
        layer: MapLayer,
        wanted: dict[str, Any],
        params: dict[str, MapParameter],
    ) -> None:
        """Sync the layer's parameter links to ``wanted`` (already
        variant-resolved — see ``_seed_layer``)."""
        wanted_slugs = set(wanted)
        existing = {
            link.parameter.slug: link
            for link in MapLayerParameter.objects.filter(layer=layer)
        }
        for param_slug in wanted_slugs - set(existing):
            if param_slug in params:
                MapLayerParameter.objects.create(
                    layer=layer,
                    parameter=params[param_slug],
                    default_override=wanted[param_slug],
                )
        for param_slug, link in existing.items():
            if param_slug not in wanted_slugs:
                link.delete()

    def _sync_categories(self, layer: MapLayer, parent: dict[str, Any]) -> None:
        from server.apps.categories.models import Category

        wanted = parent.get("categories", [])
        existing = {
            (link.category.slug, link.use): link
            for link in MapLayerCategory.objects.filter(layer=layer)
        }
        keep: set[tuple[str, str]] = set()
        for entry in wanted:
            category = Category.objects.filter(
                Q(slug=entry["slug"], parent__isnull=True)
                | Q(slug=entry["slug"].split(".")[-1])
            ).first()
            if category is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠ Category {entry['slug']!r} not found — skipping "
                        f"(seed categories first)"
                    )
                )
                continue
            key = (category.slug, entry["use"])
            keep.add(key)
            if key not in existing:
                MapLayerCategory.objects.create(
                    layer=layer,
                    category=category,
                    use=entry["use"],
                    order=entry.get("order", 0),
                )
        for key, link in existing.items():
            if key not in keep:
                link.delete()

    def _sync_attributions(
        self, layer: MapLayer, parent: dict[str, Any], orgs: dict[str, Organization]
    ) -> None:
        wanted = parent.get("attributions", [])
        existing = {
            link.organization.slug: link
            for link in MapLayerAttribution.objects.filter(layer=layer)
        }
        for idx, org_slug in enumerate(wanted):
            org = orgs.get(org_slug)
            if org is None:
                continue
            if org_slug not in existing:
                MapLayerAttribution.objects.create(
                    layer=layer, organization=org, order=idx
                )
        for org_slug, link in existing.items():
            if org_slug not in wanted:
                link.delete()
