"""Seed helpers — Python ports of the frontend overlay factories.

Mirrors ``wodore-frontend-quasar`` ``src/stores/map/utils/{raster,
overlays,overlay-huts,overlay-transport}.ts`` so ``map_seed``
provisions the current frontend definitions as database rows. Helper
functions (not fixture files) keep the small overlay styles readable
and diffable; the two big authored basemap styles (mtk/ofm) load from
fixture JSON files (``fixtures/styles/``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

GLYPHS = "{TILE_SERVER_URL}/font/{fontstack}/{range}.pbf"

SWISSTOPO_HOSTS = tuple(f"wmts{i}.geo.admin.ch" for i in range(10))


def swisstopo_wmts_urls(
    layer: str, matrix_set: int = 3857, fmt: str = "png"
) -> list[str]:
    """The ten swisstopo WMTS REST host templates (frontend parity)."""
    return [
        f"https://{host}/1.0.0/{layer}/default/current/"
        f"{matrix_set}/{{z}}/{{x}}/{{y}}.{fmt}"
        for host in SWISSTOPO_HOSTS
    ]


def waymarkedtrails_urls(kind: str) -> list[str]:
    """Waymarked Trails XYZ tiles."""
    return [f"https://tile.waymarkedtrails.org/{kind}/{{z}}/{{x}}/{{y}}.png"]


def opacity_levels(
    zoom_out: float = 0.0,
    zoom_main: float = 0.8,
    zoom_in: float = 0.3,
) -> list[Any]:
    """Port of the frontend ``opacityLevels()`` interpolate expression.

    Stops aligned with the overlay zoom floor: overlays fade in from
    z8 and adapt to street zooms by z16.
    """
    return [
        "interpolate",
        ["linear"],
        ["zoom"],
        8,
        zoom_out,
        9,
        zoom_main * 0.8,
        13,
        zoom_main,
        16,
        zoom_in,
    ]


def raster_style(
    name: str,
    tiles: list[str],
    *,
    layer_ids: list[str] | None = None,
    min_zoom: int = 0,
    max_zoom: int = 22,
    tile_size: int = 256,
    attribution: str = "",
    opacity_token: str | None = None,
) -> dict[str, Any]:
    """Port of ``getRasterStyle()`` — one raster source + layer(s)."""
    layer_ids = layer_ids or [name]
    layers: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for layer_id in layer_ids:
        paint: dict[str, Any] = {}
        if opacity_token:
            paint["raster-opacity"] = f"{{{{{opacity_token}}}}}"
        layers.append(
            {
                "id": f"wd-{layer_id}",
                "type": "raster",
                "source": f"wd-{layer_id}",
                "minzoom": min_zoom,
                "maxzoom": max_zoom,
                **({"paint": paint} if paint else {}),
            }
        )
        sources[f"wd-{layer_id}"] = {
            "type": "raster",
            "tiles": tiles,
            "tileSize": tile_size,
            **({"attribution": attribution} if attribution else {}),
        }
    return {
        "version": 8,
        "name": name,
        "sources": sources,
        "glyphs": GLYPHS,
        "layers": layers,
    }


def swisstopo_overlay_style(
    name: str,
    layer: str | list[str],
    *,
    opacity_token: str | None = None,
    min_zoom: int = 0,
) -> dict[str, Any]:
    """Port of ``getSwisstopoOverlay()`` → inline style.

    Each WMTS layer gets its own raster source (frontend parity: one
    source per swisstopo layer, ids prefixed ``wd-``).
    """
    layer_ids = [layer] if isinstance(layer, str) else layer
    layers: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for layer_id in layer_ids:
        source_id = f"wd-{layer_id}"
        paint: dict[str, Any] = {}
        if opacity_token:
            paint["raster-opacity"] = f"{{{{{opacity_token}}}}}"
        layers.append(
            {
                "id": source_id,
                "type": "raster",
                "source": source_id,
                "minzoom": min_zoom,
                **({"paint": paint} if paint else {}),
            }
        )
        sources[source_id] = {
            "type": "raster",
            "tiles": swisstopo_wmts_urls(layer_id),
            "tileSize": 256,
        }
    return {
        "version": 8,
        "name": name,
        "sources": sources,
        "glyphs": GLYPHS,
        "layers": layers,
    }


# ── Huts overlay (vector) ─────────────────────────────────────────────

HUTS_STYLE: dict[str, Any] = {
    "version": 8,
    "name": "huts",
    "sources": {
        "wd-huts": {
            "type": "vector",
            "url": "{TILE_SERVER_URL}/huts",
            "promoteId": "slug",
        },
    },
    "sprite": [{"id": "wd", "url": "{TILE_SERVER_URL}/sprite/accommodation"}],
    "glyphs": GLYPHS,
    "layers": [
        {
            "id": "wd-huts-selected",
            "type": "circle",
            "source": "wd-huts",
            "source-layer": "huts",
            "layout": {"visibility": "visible"},
            "paint": {
                "circle-blur": 0.7,
                "circle-color": [
                    "case",
                    ["boolean", ["feature-state", "color"], False],
                    ["feature-state", "color"],
                    "#2673bf",
                ],
                "circle-opacity": [
                    "case",
                    ["boolean", ["feature-state", "selected"], False],
                    0.7,
                    0,
                ],
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    10,
                    15,
                    40,
                ],
            },
        },
        {
            "id": "wd-huts",
            "type": "symbol",
            "source": "wd-huts",
            "source-layer": "huts",
            "minzoom": 5,
            "layout": {
                "text-field": [
                    "case",
                    [">", ["get", "type_standard_order"], 25],
                    ["get", "name"],
                    "",
                ],
                "text-size": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    7,
                    9,
                    10,
                    22,
                    16,
                ],
                "text-font": ["Noto Sans Bold"],
                "text-anchor": "bottom",
                "icon-allow-overlap": True,
                "text-allow-overlap": False,
                "symbol-sort-key": ["get", "type_standard_order"],
                "icon-overlap": "always",
                "text-overlap": "never",
                "text-optional": True,
                "icon-image": [
                    "step",
                    ["zoom"],
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd:simple/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd:simple/accommodation.unknown"],
                    ],
                    11,
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd:detailed/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd:detailed/accommodation.unknown"],
                    ],
                ],
                "icon-size": [
                    "*",
                    "{{huts.icon_scale}}",
                    [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        0.1,
                        9,
                        0.3,
                        20,
                        2,
                    ],
                ],
                "visibility": "visible",
            },
            "paint": {
                "icon-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    5,
                    0.7,
                    10,
                    0.8,
                    22,
                    0.85,
                ],
                "text-opacity": ["step", ["zoom"], 0, 7, 1],
                "text-halo-width": 2,
                "text-halo-color": "#ffffff",
                "text-translate": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    ["literal", [0, -6]],
                    20,
                    ["literal", [0, -40]],
                ],
            },
        },
    ],
    "metadata": {"wd:slot_layers": ["wd-huts", "wd-huts-selected"]},
}


# ── Availability overlay (split from the frontend huts overlay) ──────


def _avail_colors(day: int) -> list[Any]:
    return [
        "match",
        ["get", "occupancy_status", ["at", day, ["get", "data"]]],
        "empty",
        "#25BF5E",
        "low",
        "#F6AD4B",
        "medium",
        "#EA9A37",
        "free_unknown",
        "#7FAB88",
        "high",
        "#C3731F",
        "full",
        "#961A17",
        "rgba(0,0,0,0)",
    ]


def _occupation_day_layer(day: int) -> dict[str, Any]:
    def occ_translate(day: int) -> list[Any]:
        return [
            "interpolate",
            ["linear"],
            ["zoom"],
            9,
            [
                "literal",
                [(day - 1.5) * 7, 11 + abs(day - 1.5) * -2],
            ],
            20,
            [
                "literal",
                [(day - 1.5) * 40, 90 + abs(day - 1.5) * -10],
            ],
        ]

    return {
        "id": f"wd-huts-occupation-day{day}",
        "type": "symbol",
        "source": "wd-bookings",
        "minzoom": 6,
        "layout": {
            "visibility": "visible",
            "text-field": [
                "case",
                ["<", day, ["length", ["get", "data"]]],
                [
                    "concat",
                    [
                        "case",
                        [
                            "==",
                            ["get", "free", ["at", day, ["get", "data"]]],
                            None,
                        ],
                        "?",
                        [
                            "to-string",
                            ["get", "free", ["at", day, ["get", "data"]]],
                        ],
                    ],
                    "\n",
                    [
                        "case",
                        [
                            "==",
                            ["get", "total", ["at", day, ["get", "data"]]],
                            None,
                        ],
                        "?",
                        [
                            "to-string",
                            ["get", "total", ["at", day, ["get", "data"]]],
                        ],
                    ],
                ],
                "",
            ],
            "text-size": ["interpolate", ["linear"], ["zoom"], 12, 7, 14, 10],
            "text-font": ["Noto Sans Bold"],
            "icon-allow-overlap": True,
            "text-allow-overlap": True,
            "icon-image": [
                "coalesce",
                [
                    "image",
                    [
                        "concat",
                        "wd:detailed/availability.",
                        [
                            "case",
                            ["<", day, ["length", ["get", "data"]]],
                            [
                                "get",
                                "occupancy_status",
                                ["at", day, ["get", "data"]],
                            ],
                            "unknown",
                        ],
                    ],
                ],
                ["image", "wd:detailed/availability.unknown"],
            ],
            "icon-size": [
                "interpolate",
                ["linear"],
                ["zoom"],
                7,
                0.1,
                12,
                0.3,
                15,
                0.6,
            ],
        },
        "paint": {
            "icon-translate": occ_translate(day),
            "text-translate": occ_translate(day),
            "text-opacity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                9,
                0,
                10,
                0.4,
                12,
                0.6,
            ],
            "icon-opacity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                6,
                0,
                8,
                0.8,
                9,
                1,
                11,
                1,
                13,
                0.7,
            ],
        },
    }


AVAILABILITY_STYLE: dict[str, Any] = {
    "version": 8,
    "name": "huts-availability",
    "sources": {
        "wd-bookings": {
            "type": "geojson",
            "data": "{API_URL}/v1/huts/availability/{{date}}.geojson",
            "promoteId": "hut_id",
        },
    },
    "sprite": [{"id": "wd", "url": "{TILE_SERVER_URL}/sprite/availability"}],
    "glyphs": GLYPHS,
    "layers": [
        _occupation_day_layer(0),
        _occupation_day_layer(1),
        _occupation_day_layer(2),
        _occupation_day_layer(3),
        {
            "id": "wd-huts-occupation",
            "type": "circle",
            "source": "wd-bookings",
            "maxzoom": 13,
            "layout": {"visibility": "visible"},
            "paint": {
                "circle-color": _avail_colors(0),
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    4,
                    9,
                    10,
                    20,
                    60,
                ],
                "circle-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    4,
                    0.8,
                    8,
                    0.6,
                    9,
                    0.5,
                    11,
                    0,
                ],
            },
        },
    ],
}


# ── Transport stops overlay (external geojson) ────────────────────────

TRANSPORT_STYLE: dict[str, Any] = {
    "version": 8,
    "name": "transport-stops",
    "sources": {
        "transport-stops": {
            "type": "geojson",
            "data": (
                "https://raw.githubusercontent.com/wodore/bav-haltestellen/"
                "main/static/bav_list.geojson"
            ),
            "promoteId": "id",
        },
    },
    "glyphs": GLYPHS,
    "layers": [
        {
            "id": "transport-stops",
            "type": "circle",
            "source": "transport-stops",
            "layout": {"visibility": "visible"},
            "paint": {
                "circle-color": [
                    "case",
                    ["in", "train", ["get", "types"]],
                    "#C60018",
                    ["in", "bus", ["get", "types"]],
                    "#2d327d",
                    "#0079C7",
                ],
                "circle-stroke-color": "#F6F6F6",
                "circle-stroke-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    10,
                    0,
                    12,
                    1,
                    16,
                    2,
                ],
                "circle-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    [
                        "case",
                        ["in", "train", ["get", "types"]],
                        3,
                        ["in", "bus", ["get", "types"]],
                        2,
                        1,
                    ],
                    9,
                    [
                        "case",
                        ["in", "train", ["get", "types"]],
                        4,
                        ["in", "bus", ["get", "types"]],
                        3,
                        3,
                    ],
                    16,
                    [
                        "case",
                        ["in", "train", ["get", "types"]],
                        9,
                        ["in", "bus", ["get", "types"]],
                        8,
                        8,
                    ],
                ],
                "circle-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    4,
                    0,
                    5,
                    0.3,
                    8,
                    0.6,
                    12,
                    1,
                ],
            },
        },
    ],
}


def osm_raster_style() -> dict[str, Any]:
    """Keyless OSM raster (weak-GPU variant, frontend parity)."""
    return raster_style(
        "osm-raster",
        [
            f"https://{host}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png"
            for host in ("a", "b", "c")
        ],
        attribution="© OpenStreetMap contributors",
    )


def swisstopo_pixelkarte_style() -> dict[str, Any]:
    """CH pixelkarte raster (country-only basemap, frontend parity)."""
    return raster_style(
        "ch-swisstopo-raster",
        swisstopo_wmts_urls("ch.swisstopo.pixelkarte-farbe"),
        attribution="swisstopo",
    )


def tile_server_url() -> str:
    """The Martin origin used for placeholder resolution at serve time."""
    return getattr(settings, "MARTIN_TILE_URL", "") or ""
