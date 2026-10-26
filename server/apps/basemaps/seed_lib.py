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

from server.apps.envvars.registry import resolve_setting

# Canonical Martin glyph route, extension-less ON PURPOSE: Martin 301s
# `/font/{stack}/{range}.pbf` to this route while DROPPING the query
# string (martin <= 1.16.1 `redirect_font_ext`), so a `.pbf` template
# would strip the serve-time `?v=` asset version off every glyph
# request — an extra redirect round-trip per fontstack/range and a
# cache key that never rotates on font changes. The canonical route
# answers 200 directly with the query intact.
GLYPHS = "{{env:MARTIN_TILE_URL}}/font/{fontstack}/{range}"

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


# ── Huts + availability overlay (vector + vector, frontend parity) ──
#
# Mirrors the CURRENT frontend ``hutsStyle`` (overlay-huts.ts): one style,
# both sources. Availability rides the Martin ``availability`` function
# source (backend #341): one MVT feature per hut with the per-day series
# flattened into scalar props — expressions read them with literal day
# keys (``d{day}_status`` …), the feature-level ``days`` prop replaces the
# old ``["length", ["get", "data"]]`` guard. Sprites match what Martin
# serves from the database category sync (``color/``, ``mono/``,
# ``primitive/`` variants — there is no ``simple/``/``detailed/``
# variant) plus the SDF sprite for runtime-tinted mono glyphs.


def _avail_colors(day: int) -> list[Any]:
    return [
        "match",
        ["get", f"d{day}_status"],
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
    """One day column of the availability strip (frontend parity)."""

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
        "source-layer": "availability",
        "minzoom": 6,
        "layout": {
            "visibility": "visible",
            "text-field": [
                "case",
                ["<", day, ["get", "days"]],
                [
                    "case",
                    # Unknown day: a single "?" — the source reports
                    # free=0/total=0 with no real counts, so "0\n0"
                    # would be misleading.
                    ["==", ["get", f"d{day}_status"], "unknown"],
                    "?",
                    [
                        "concat",
                        # the free/total props are absent if the source
                        # does not publish the count (free_unknown)
                        [
                            "case",
                            ["==", ["get", f"d{day}_free"], None],
                            "?",
                            ["to-string", ["get", f"d{day}_free"]],
                        ],
                        "\n",
                        [
                            "case",
                            ["==", ["get", f"d{day}_total"], None],
                            "?",
                            ["to-string", ["get", f"d{day}_total"]],
                        ],
                    ],
                ],
                "",
            ],
            "text-size": ["interpolate", ["linear"], ["zoom"], 12, 7, 14, 10],
            # Match the wd-outdoor-base-mtk basemap typography (place-label
            # voice + non-latin fallback, same Martin glyph endpoint).
            "text-font": ["Barlow Semi Condensed SemiBold", "Noto Sans Bold"],
            "icon-allow-overlap": True,
            "text-allow-overlap": True,
            "icon-image": [
                "coalesce",
                [
                    "image",
                    [
                        "concat",
                        "wd:color/availability.",
                        [
                            "case",
                            ["<", day, ["get", "days"]],
                            ["get", f"d{day}_status"],
                            "unknown",
                        ],
                    ],
                ],
                ["image", "wd:color/availability.unknown"],
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
            # The wd-outdoor-base-mtk style's standard pale halo — keeps
            # the numbers readable where dots overlap terrain labels.
            "text-halo-color": "rgba(242, 247, 244, 0.9)",
            "text-halo-width": 0.8,
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


HUTS_STYLE: dict[str, Any] = {
    "version": 8,
    "name": "huts",
    "sources": {
        "wd-huts": {
            "type": "vector",
            # Inline tiles (not the TileJSON link) so the served style
            # can carry the serve-time ``?v=`` asset version on every
            # tile URL — Martin's TileJSON builds its own tiles list and
            # a version on the link would never reach it. minzoom 5 /
            # maxzoom 16 mirror the Martin table config (z5 = the
            # full-country overlay floor, OVERLAY_MIN_ZOOM).
            # MLT v1: the .mlt URL space (tile-router → Martin serve-time
            # conversion, `convert_to_mlt` in martin.yaml) plus the
            # MapLibre decoder marker. Pairing contract (tested): a
            # .mlt tiles template always ships with ``encoding: mlt``.
            "tiles": ["{{env:MARTIN_TILE_URL}}/huts/{z}/{x}/{y}.mlt"],
            "encoding": "mlt",
            "minzoom": 5,
            # Overzoom cap (matches the Martin table): symbols re-place
            # instantly from z9 ancestors on deeper zooms — no new tiles,
            # so zoom icon updates never queue behind basemap/terrain loads.
            "maxzoom": 9,
            "promoteId": "slug",
        },
        "wd-bookings": {
            # Martin ``availability`` function source (backend #341):
            # get_availability_for_tiles — one MVT feature per hut, the
            # per-day series flattened into dN_* scalar props. ``{{date}}``
            # is the runtime date token (frontend resolves it and pushes
            # tile-URL updates on date changes via setTiles); days=4
            # matches the four day-column layers; below zoom 7 the server
            # serves only day 0. maxzoom 9: deeper zooms overzoom the z9
            # tiles client-side (no further requests).
            # MLT v1 like wd-huts: explicit .mlt URL space (tile-router
            # strips the suffix and keeps the date/days query) plus the
            # MapLibre decoder marker. Pairing contract (tested): a .mlt
            # tiles template always ships with ``encoding: mlt``.
            "type": "vector",
            "tiles": [
                "{{env:MARTIN_TILE_URL}}/availability/{z}/{x}/{y}.mlt?date={{date}}&days=4"
            ],
            "encoding": "mlt",
            "promoteId": "slug",
            "minzoom": 5,
            "maxzoom": 9,
        },
    },
    "sprite": [
        # Martin serves the DB-synced category sprites; the combined URL
        # merges accommodation + availability under the "wd" id, and the
        # SDF variant carries runtime-tintable mono silhouettes.
        {
            "id": "wd",
            "url": "{{env:MARTIN_TILE_URL}}/sprite/accommodation,availability",
        },
        {"id": "wd-sdf", "url": "{{env:MARTIN_TILE_URL}}/sdf_sprite/accommodation"},
    ],
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
            "source-layer": "availability",
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
                # Legible floor (the old 7px was sub-legible), capped
                # like the basemap's own labels.
                "text-size": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    8.5,
                    10,
                    11,
                    14,
                    13.5,
                    17,
                    15,
                ],
                # The brand label font and the basemap's place/peak label
                # voice; Noto Sans Bold stays as the non-latin fallback.
                "text-font": ["Barlow Semi Condensed SemiBold", "Noto Sans Bold"],
                "text-anchor": "bottom",
                "icon-allow-overlap": True,
                "text-allow-overlap": False,
                "symbol-sort-key": ["get", "type_standard_order"],
                "icon-overlap": "always",
                "text-overlap": "never",
                "text-optional": True,
                # Zoom ladder: primitive (far out, tiny) → mono SDF
                # (zoomed in, runtime-tinted). Below z9 the primitive
                # sprite (small colored shape on white ring) reads
                # better than a glyph at ~5px; from z9 up the SDF mono
                # glyph with runtime tinting and a white halo border is
                # the workhorse.
                "icon-image": [
                    "step",
                    ["zoom"],
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd:primitive/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd:primitive/accommodation.unknown"],
                        # Fallback to mono if primitive isn't served
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:mono/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:mono/accommodation.unknown"],
                    ],
                    9,
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:mono/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:mono/accommodation.unknown"],
                        [
                            "image",
                            [
                                "concat",
                                "wd:primitive/",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd:primitive/accommodation.unknown"],
                    ],
                ],
                # 48px art. Far out: small (0.1–0.3 like the original).
                # Zoomed in: the glyph fills the space (0.5–1.25).
                "icon-size": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    ["*", 0.1, "{{huts.icon_scale}}"],
                    9,
                    ["*", 0.3, "{{huts.icon_scale}}"],
                    11,
                    ["*", 0.55, "{{huts.icon_scale}}"],
                    13,
                    ["*", 0.75, "{{huts.icon_scale}}"],
                    16,
                    ["*", 1.0, "{{huts.icon_scale}}"],
                    20,
                    ["*", 1.25, "{{huts.icon_scale}}"],
                ],
                "visibility": "visible",
            },
            "paint": {
                # SDF runtime tinting: type color from the tiles, white
                # border around it.
                "icon-color": [
                    "coalesce",
                    ["get", "type_standard_color"],
                    "#718096",
                ],
                "icon-halo-color": "#ffffff",
                "icon-halo-width": 2,
                "icon-halo-blur": 0.15,
                # Semi-transparent when zoomed out, full opacity when
                # zoomed in.
                "icon-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    5,
                    0.7,
                    10,
                    0.8,
                    13,
                    0.9,
                    16,
                    1,
                ],
                "text-opacity": ["step", ["zoom"], 0, 7, 1],
                # Forest-deep (#224E3B) marks hut names as the product's
                # own objects; halo = the style's standard pale
                # green-white (AA on light imagery).
                "text-color": "#224E3B",
                "text-halo-width": 1.2,
                "text-halo-color": "rgba(242, 247, 244, 0.9)",
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
    "metadata": {
        "wd:slot_layers": [
            "wd-huts-occupation-day0",
            "wd-huts-occupation-day1",
            "wd-huts-occupation-day2",
            "wd-huts-occupation-day3",
            "wd-huts-occupation",
            "wd-huts-selected",
            "wd-huts",
        ],
    },
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
    """CH pixelkarte raster (country-only basemap, frontend parity).

    The pixelkarte WMTS serves JPEG — the default PNG template 400s and
    the basemap shows nothing (verified against wmts.geo.admin.ch).
    """
    return raster_style(
        "ch-swisstopo-raster",
        swisstopo_wmts_urls("ch.swisstopo.pixelkarte-farbe", fmt="jpeg"),
        attribution="swisstopo",
    )


def tile_server_url() -> str:
    """The Martin origin used for placeholder resolution at serve time."""
    return resolve_setting("MARTIN_TILE_URL")
