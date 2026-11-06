"""Seed helpers — Python ports of the frontend overlay factories.

Mirrors ``wodore-frontend-quasar`` ``src/stores/map/utils/{raster,
overlays,overlay-huts,overlay-transport}.ts`` so ``map_seed``
provisions the current frontend definitions as database rows. Helper
functions (not fixture files) keep the small overlay styles readable
and diffable; the two big authored basemap styles (mtk/ofm) load from
fixture JSON files (``fixtures/styles/``).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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
                        "wd:color/amenity.availability.",
                        [
                            "case",
                            ["<", day, ["get", "days"]],
                            ["get", f"d{day}_status"],
                            "unknown",
                        ],
                    ],
                ],
                ["image", "wd:color/amenity.availability.unknown"],
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
                # Zoom ladder: primitive shape (far out, tiny) →
                # mono glyph (zoomed in). BOTH run through the SDF sprite
                # so the paint props apply at every zoom: icon-color tints
                # with the per-type color from the tiles and icon-halo-*
                # draws the white border. The regular (non-SDF) ``wd``
                # primitive sprite is NOT usable here: its SVGs use
                # fill="currentColor", which Martin rasterizes to black,
                # and non-SDF icons ignore icon-color entirely (the black
                # far-zoom icons bug). Below z9 the simpler primitive
                # shape reads better at ~5px than the detailed mono
                # glyph; from z9 up the mono glyph is the workhorse.
                "icon-image": [
                    "step",
                    ["zoom"],
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:primitive/amenity.",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:primitive/amenity.accommodation.unknown"],
                        # Fallback to mono if primitive isn't served
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:mono/amenity.",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:mono/amenity.accommodation.unknown"],
                    ],
                    9,
                    [
                        "coalesce",
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:mono/amenity.",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:mono/amenity.accommodation.unknown"],
                        [
                            "image",
                            [
                                "concat",
                                "wd-sdf:primitive/amenity.",
                                ["get", "type_standard_identifier"],
                            ],
                        ],
                        ["image", "wd-sdf:primitive/amenity.accommodation.unknown"],
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
                # Halo width is ABSOLUTE device pixels — it does NOT
                # scale with icon-size (style spec). A constant 2px on
                # the ~14px glyphs around z9 (icon-size 0.3) merged the
                # per-stroke outlines into one solid white plate; the
                # same 2px only becomes a thin border at z13+ (36-48px
                # glyphs) — the “plate at mid zoom, gone when zoomed
                # in” bug. The ladder tracks the icon-size ramp so the
                # border stays proportionally thin at every zoom.
                "icon-halo-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    0.5,
                    9,
                    0.75,
                    11,
                    1.0,
                    13,
                    1.5,
                    16,
                    2.0,
                    20,
                    2.5,
                ],
                # No blur: the 0.15 fade made the border read as a soft
                # translucent glow (and added to the SDF softness).
                "icon-halo-blur": 0,
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


def _huts_style_subset() -> dict[str, Any]:
    """Build the subset twin of ``HUTS_STYLE`` (Leaflet fallback).

    Deliberate surgery, not a blanket copy — the full document's seven
    layers sort into three classes against subset v0.1:

    * **kept verbatim** (minus the default ``layout.visibility``):
      ``wd-huts-occupation`` — the availability disc, whose
      ``match``-on-``d0_status`` color is the proven-expressible core
      the fallback's status palette consumes. Both vector MLT sources
      stay (the fallback reads ``wd-bookings`` for availability), with
      ``promoteId`` stripped (clients key features by the
      tile-provided id).
    * **kept trimmed**: ``wd-huts`` — the per-category icon ladder
      (``step``/``coalesce``/``image``/``concat``), the label text
      (``>`` comparison in ``text-field``) and SDF halo paints are
      outside the whitelist. The twin keeps a STATIC fallback sprite
      (``wd-sdf:mono/amenity.accommodation.unknown``, runtime-tinted per type
      via a ``case``/``has``/``get`` ``icon-color``), bakes the
      ``icon-size`` zoom ladder at the default multiplier (the
      ``huts.icon_scale`` parameter rides on ``*``, not whitelisted),
      and drops text entirely — the fallback draws labels itself via
      canvas fonts, and per-category icons client-side
      (``config.clustering``'s ``iconProperty``).
    * **dropped**: the ``wd-huts-occupation-day0..3`` strip columns
      (``<``/``concat``/``to-string``/``image`` — the fallback renders
      the per-day detail in its own panel) and ``wd-huts-selected``
      (``feature-state`` — selection is app-driven client state, not
      style).
    """
    occupation = next(
        layer for layer in HUTS_STYLE["layers"] if layer["id"] == "wd-huts-occupation"
    )
    huts = next(layer for layer in HUTS_STYLE["layers"] if layer["id"] == "wd-huts")
    return {
        "version": 8,
        "name": "huts",
        "sources": {
            source_id: {
                key: value for key, value in source.items() if key != "promoteId"
            }
            for source_id, source in HUTS_STYLE["sources"].items()
        },
        "sprite": deepcopy(HUTS_STYLE["sprite"]),
        "glyphs": GLYPHS,
        "layers": [
            {
                key: deepcopy(value)
                for key, value in occupation.items()
                if key != "layout"
            },
            {
                **{
                    key: deepcopy(value)
                    for key, value in huts.items()
                    if key not in ("layout", "paint")
                },
                "layout": {
                    "icon-allow-overlap": True,
                    "icon-image": "wd-sdf:mono/amenity.accommodation.unknown",
                    "icon-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        0.1,
                        9,
                        0.3,
                        11,
                        0.55,
                        13,
                        0.75,
                        16,
                        1.0,
                        20,
                        1.25,
                    ],
                },
                "paint": {
                    "icon-color": [
                        "case",
                        ["has", "type_standard_color"],
                        ["get", "type_standard_color"],
                        "#718096",
                    ],
                    "icon-opacity": deepcopy(huts["paint"]["icon-opacity"]),
                },
            },
        ],
        "metadata": {"wd:slot_layers": ["wd-huts-occupation", "wd-huts"]},
    }


#: Subset twin of HUTS_STYLE — derived once at import so a future
#: non-whitelisted key in the surviving layers fails the seed gate
#: loudly instead of the twin silently drifting (transport-stops
#: pattern, #443).
HUTS_STYLE_SUBSET: dict[str, Any] = _huts_style_subset()


# ── Accommodations overlay (geoplaces function source via Martin) ───

#: The Martin function source id (``functions.geoplaces`` in
#: ``tile_server/config/martin.yaml``): ``get_geoplaces_for_tiles``
#: serves one feature per public+active categorized place with
#: SERVER-side clustering below the raw floor (count>1 features are
#: grid clusters of the primary category; the transition zone graduates
#: high-importance POIs raw early). Tile URL params (see the martin.yaml
#: comment block / ``geometries/models/tiles_view.py`` for the full
#: contract):
#:   category_tree=accommodation  subtree filter — the OSM import links
#:                                LEAF categories only (hotel, campgr,
#:                                …), the filter matches the linked
#:                                category's kind, contract group or
#:                                domain, so the whole accommodation
#:                                group (under the amenity domain) is one
#:                                param
#:   fields=…                    flat color/parent_slug/category_identifier
#:                                props + the categories array; sources
#:                                stay off (place detail is fetched by
#:                                slug)
#:   max_label_zoom=11            names ride the tiles from z11 (default
#:                                14 — labels are the point of this
#:                                overlay)
#:   cluster_max_zoom=7            full clustering z5–z7, transition
#:                                z8–z9 (isolated points go raw early),
#:                                every place individual from z10 — the
#:                                function default (6) graduated clusters
#:                                one zoom too early for a z5-floor
#:                                overlay (default offset 2 kept)
#:   cache_ttl_days=1             DB tile cache TTL — a POI edit shows
#:                                within a day without manual purges
#: The URL carries a query string; geoplaces is REGISTERED in
#: ``VERSIONED_TILE_SOURCES`` so the serve-time asset versioning still
#: appends ``&v=`` (a data re-seed rotates it; freshness is bounded by
#: the TTL + the 1-day edge cache_control between rotations).
GEOPLACES_SOURCE = "geoplaces"
ACCOMMODATIONS_SOURCE_ID = "wd-accommodations"

#: Sprite pack: the SDF mono+primitive silhouettes of the accommodation
#: collection (the same pack the huts overlay loads as ``wd-sdf``),
#: under this overlay's OWN id — sprite ids are add-once on the
#: frontend, a shared id would let whichever pack loads first shadow the
#: other (transport lesson, see TRANSPORT_SPRITE_ID).
ACCOMMODATIONS_SPRITE_ID = "wd-sdf-accommodations"
ACCOMMODATIONS_ICON_FALLBACK = (
    "wd-sdf-accommodations:mono/amenity.accommodation.unknown"
)

#: Flat primary-category props the tiles carry (mirror of the function's
#: raw/cluster projections).
_ACCOMMODATION_COUNT_FILTER = ["==", ["get", "count"], 1]
_ACCOMMODATION_CLUSTER_FILTER = [">", ["get", "count"], 1]


_AMENITY_ICON_SIZE_STOPS: list[tuple[int, float]] = [
    (7, 0.1),
    (9, 0.3),
    (11, 0.55),
    (13, 0.75),
    (16, 1.0),
    (20, 1.25),
]

#: Cluster nodes render the SAME per-kind icon as individuals, NO
#: count labels — slightly bigger, scaled by member count: 1.1× at
#: count 2 → 1.8× at count ≥ 12 (MapLibre ``interpolate`` clamps
#: beyond the outer stops; membership itself comes from
#: ``GET /v1/geoplaces/near`` on click, never from the tile).
_CLUSTER_COUNT_SCALE: list[Any] = [
    "interpolate",
    ["linear"],
    ["get", "count"],
    2,
    1.1,
    12,
    1.8,
]

#: Subset twins cannot multiply the zoom ladder by the count scale
#: (the Leaflet-class whitelist has no ``*`` operator) — their cluster
#: icons render ~1.35× the raw size at every zoom, count-independent
#: (degraded profile; the full profile scales by count).
_AMENITY_CLUSTER_ICON_SIZE_STOPS: list[tuple[int, float]] = [
    (zoom, round(size * 1.35, 3)) for zoom, size in _AMENITY_ICON_SIZE_STOPS
]


def _size_ladder(stops: list[tuple[int, float]]) -> list[Any]:
    """Flatten (zoom, size) stops into an interpolate expression."""
    flat: list[Any] = []
    for zoom, size in stops:
        flat.extend((zoom, size))
    return ["interpolate", ["linear"], ["zoom"], *flat]


_AMENITY_HALO_STOPS: list[tuple[int, float]] = [
    (7, 0.5),
    (9, 0.75),
    (11, 1.0),
    (13, 1.5),
    (16, 2.0),
    (20, 2.5),
]
_AMENITY_TEXT_SIZE_STOPS: list[tuple[int, float]] = [
    (11, 10),
    (14, 12.5),
    (17, 14),
]


def accommodations_style() -> dict[str, Any]:
    """The accommodations overlay style — the huts look on POI data.

    Same visual grammar as :data:`HUTS_STYLE` (mono SDF icons tinted by
    category color with the white halo ladder, Barlow Semi Condensed
    labels, selection circle, ``{{<slug>.icon_scale}}`` parameter),
    minus everything availability-specific (day strips, occupation
    disc — geoplaces carry no availability) and plus the server-side
    cluster rendering the function source provides:

    * z5–z7 (function's full-clustering zone, ``cluster_max_zoom=7``):
      category-colored cluster bubbles with member counts — one per
      (category, grid cell);
    * z8–z9 transition: high-importance places already raw (icons) while
      the rest still clusters;
    * z10+: raw icons + labels for every place (names from z11 via
      ``max_label_zoom``), icon ladder primitive → mono like the huts.
    """
    icon_ladder = [
        "step",
        ["zoom"],
        [
            "coalesce",
            [
                "image",
                [
                    "concat",
                    "wd-sdf-accommodations:primitive/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", ACCOMMODATIONS_ICON_FALLBACK],
            [
                "image",
                [
                    "concat",
                    "wd-sdf-accommodations:mono/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", ACCOMMODATIONS_ICON_FALLBACK],
        ],
        9,
        [
            "coalesce",
            [
                "image",
                [
                    "concat",
                    "wd-sdf-accommodations:mono/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", ACCOMMODATIONS_ICON_FALLBACK],
            [
                "image",
                [
                    "concat",
                    "wd-sdf-accommodations:primitive/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", ACCOMMODATIONS_ICON_FALLBACK],
        ],
    ]

    return {
        "version": 8,
        "name": "accommodations",
        "sources": {
            ACCOMMODATIONS_SOURCE_ID: {
                "type": "vector",
                # Inline tiles + MLT like wd-huts (serve-time MVT→MLT on
                # the explicit .mlt URL space; the tile-router strips the
                # suffix and forwards the query). minzoom 5 = the overlay
                # floor; maxzoom 14 — nothing new beyond (names arrive at
                # z11, symbols re-place from z14 ancestors on deeper
                # zooms, no further requests).
                "tiles": [
                    (
                        "{{env:MARTIN_TILE_URL}}/geoplaces/{z}/{x}/{y}.mlt"
                        "?category_tree=accommodation"
                        # flat color/parent/category_identifier props plus
                        # elevation (popups) — the `category` object and
                        # `categories` array are opt-in fields and stay off
                        # (they dominate tile size; nothing in this
                        # document reads them)
                        "&fields=color,parent_color,parent_slug,"
                        "category_identifier,importance,count,name,slug,"
                        "elevation"
                        "&max_label_zoom=11&cluster_max_zoom=7"
                        "&cache_ttl_days=1"
                    )
                ],
                "encoding": "mlt",
                "minzoom": 5,
                "maxzoom": 14,
                "promoteId": "slug",
            },
        },
        "sprite": [
            {
                "id": ACCOMMODATIONS_SPRITE_ID,
                "url": "{{env:MARTIN_TILE_URL}}/sdf_sprite/accommodation",
            }
        ],
        "glyphs": GLYPHS,
        "layers": [
            {
                # Server-side clusters (count>1): the SAME per-kind icon
                # as individuals — no count labels, slightly bigger with
                # member count (1.1× at 2 → 1.8× at ≥ 12; membership
                # comes from GET /v1/geoplaces/near on click). The
                # decluttered country view until the raw icons graduate.
                "id": "wd-accommodations-clusters",
                "type": "symbol",
                "source": ACCOMMODATIONS_SOURCE_ID,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": 5,
                "filter": _ACCOMMODATION_CLUSTER_FILTER,
                "layout": {
                    "icon-image": icon_ladder,
                    "icon-size": [
                        "*",
                        [
                            "interpolate",
                            ["linear"],
                            ["zoom"],
                            7,
                            ["*", 0.1, "{{accommodations.icon_scale}}"],
                            9,
                            ["*", 0.3, "{{accommodations.icon_scale}}"],
                            11,
                            ["*", 0.55, "{{accommodations.icon_scale}}"],
                            13,
                            ["*", 0.75, "{{accommodations.icon_scale}}"],
                            16,
                            ["*", 1.0, "{{accommodations.icon_scale}}"],
                            20,
                            ["*", 1.25, "{{accommodations.icon_scale}}"],
                        ],
                        _CLUSTER_COUNT_SCALE,
                    ],
                    "icon-allow-overlap": True,
                    "icon-overlap": "always",
                    "symbol-sort-key": ["get", "importance"],
                },
                "paint": {
                    "icon-color": ["coalesce", ["get", "color"], "#718096"],
                    "icon-halo-color": "#ffffff",
                    "icon-halo-width": 1.5,
                    "icon-halo-blur": 0,
                    "icon-opacity": 0.85,
                },
            },
            {
                # Selection halo (app-driven feature-state, same shape as
                # wd-huts-selected).
                "id": "wd-accommodations-selected",
                "type": "circle",
                "source": ACCOMMODATIONS_SOURCE_ID,
                "source-layer": GEOPLACES_SOURCE,
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
                "id": "wd-accommodations",
                "type": "symbol",
                "source": ACCOMMODATIONS_SOURCE_ID,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": 5,
                "filter": _ACCOMMODATION_COUNT_FILTER,
                "layout": {
                    # Raw places only (count==1); names are '' server-side
                    # below z11 (max_label_zoom) so the text simply never
                    # renders there.
                    "text-field": ["get", "name"],
                    "text-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        11,
                        10,
                        14,
                        12.5,
                        17,
                        14,
                    ],
                    "text-font": ["Barlow Semi Condensed SemiBold", "Noto Sans Bold"],
                    "text-anchor": "bottom",
                    "icon-allow-overlap": True,
                    "text-allow-overlap": False,
                    "symbol-sort-key": ["get", "importance"],
                    "icon-overlap": "always",
                    "text-overlap": "never",
                    "text-optional": True,
                    "icon-image": icon_ladder,
                    "icon-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        ["*", 0.1, "{{accommodations.icon_scale}}"],
                        9,
                        ["*", 0.3, "{{accommodations.icon_scale}}"],
                        11,
                        ["*", 0.55, "{{accommodations.icon_scale}}"],
                        13,
                        ["*", 0.75, "{{accommodations.icon_scale}}"],
                        16,
                        ["*", 1.0, "{{accommodations.icon_scale}}"],
                        20,
                        ["*", 1.25, "{{accommodations.icon_scale}}"],
                    ],
                    "visibility": "visible",
                },
                "paint": {
                    # SDF runtime tinting: category color from the tiles,
                    # white border around it (huts parity).
                    "icon-color": ["coalesce", ["get", "color"], "#718096"],
                    "icon-halo-color": "#ffffff",
                    "icon-halo-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        0.5,
                        9,
                        0.75,
                        11,
                        1.0,
                        13,
                        1.5,
                        16,
                        2.0,
                        20,
                        2.5,
                    ],
                    "icon-halo-blur": 0,
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
                    "text-opacity": ["step", ["zoom"], 0, 11, 1],
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
                "wd-accommodations-clusters",
                "wd-accommodations-selected",
                "wd-accommodations",
            ],
        },
    }


def _accommodations_style_subset() -> dict[str, Any]:
    """Build the subset twin of the accommodations overlay (Leaflet).

    Same surgery classes as the huts twin (:func:`_huts_style_subset`):

    * **kept trimmed**: the cluster bubbles (zoom-only radius ladder —
      the count-scaled nested interpolate and the white stroke are
      outside subset v0.1) and the raw symbol — STATIC fallback sprite
      (``mono/amenity.accommodation.unknown``), runtime-tinted by the
      category color via ``case``/``has``/``get``, baked icon-size
      ladder (the ``icon_scale`` parameter rides on ``*``, not
      whitelisted). No text (the fallback draws labels client-side).
    * **dropped**: the cluster count labels (``to-string``), the
      feature-state selection circle.
    """
    return {
        "version": 8,
        "name": "accommodations",
        "sources": {
            ACCOMMODATIONS_SOURCE_ID: {
                key: value
                for key, value in accommodations_style()["sources"][
                    ACCOMMODATIONS_SOURCE_ID
                ].items()
                if key != "promoteId"
            }
        },
        "sprite": deepcopy(accommodations_style()["sprite"]),
        "glyphs": GLYPHS,
        "layers": [
            {
                # Cluster icons (count-independent here — the subset
                # whitelist has no ``*`` to scale by count; ~1.35× the
                # raw size at every zoom).
                "id": "wd-accommodations-clusters",
                "type": "symbol",
                "source": ACCOMMODATIONS_SOURCE_ID,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": 5,
                "filter": _ACCOMMODATION_CLUSTER_FILTER,
                "layout": {
                    "icon-image": ACCOMMODATIONS_ICON_FALLBACK,
                    "icon-size": _size_ladder(_AMENITY_CLUSTER_ICON_SIZE_STOPS),
                    "icon-allow-overlap": True,
                },
                "paint": {
                    "icon-color": [
                        "case",
                        ["has", "color"],
                        ["get", "color"],
                        "#718096",
                    ],
                    "icon-opacity": 0.85,
                },
            },
            {
                "id": "wd-accommodations",
                "type": "symbol",
                "source": ACCOMMODATIONS_SOURCE_ID,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": 5,
                "filter": _ACCOMMODATION_COUNT_FILTER,
                "layout": {
                    "icon-image": ACCOMMODATIONS_ICON_FALLBACK,
                    "icon-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        7,
                        0.1,
                        9,
                        0.3,
                        11,
                        0.55,
                        13,
                        0.75,
                        16,
                        1.0,
                        20,
                        1.25,
                    ],
                    "icon-allow-overlap": True,
                },
                "paint": {
                    "icon-color": [
                        "case",
                        ["has", "color"],
                        ["get", "color"],
                        "#718096",
                    ],
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
                },
            },
        ],
        "metadata": {
            "wd:slot_layers": ["wd-accommodations-clusters", "wd-accommodations"]
        },
    }


#: Full accommodations overlay document (fallback palette baked at
#: import; tests import this — the seed re-uses the builder directly).
ACCOMMODATIONS_STYLE: dict[str, Any] = accommodations_style()

#: Subset twin — derived once at import so drift fails the seed gate
#: loudly (huts/transport pattern).
ACCOMMODATIONS_STYLE_SUBSET: dict[str, Any] = _accommodations_style_subset()


# ── Amenity overlay family (geoplaces per-subtree, importance bands) ─


#: Everything the generic builder needs per subtree. The bands are
#: IMPORTANCE-scaled (live staging counts/averages, verified 2026-11-03):
#:
#:   tier A (avg importance >= 50) — restaurant (51.2, 23k),
#:       health_and_emergency (54.7, 7k), outdoor_services (63.9, 4k):
#:       min_zoom 5, cluster_max_zoom 7 — accommodation parity (clusters
#:       z5–7, transition z8–9, individual z10+).
#:   tier B (~30–50) — groceries (45.1), shopping (38.3), services (35.0),
#:       finance (33.5), tourism (29.5, 45k places but low importance):
#:       min_zoom 9, cluster_max_zoom 9 — bubbles at first appearance,
#:       individual z12+.
#:   tier C (< 30) — utilities (26.0: toilets, drinking water —
#:       "only visible when zoomed in close"), automotive (14.2, 44k):
#:       min_zoom 13, cluster_max_zoom 11 — hybrid at the floor (dense
#:       pockets clustered, isolated points raw), individual z14+.
#:
#: Sprites: every subtree collection serves an SDF pack at
#: ``/sdf_sprite/<subtree>`` (martin_sync generates them from DB
#: categories; verified on staging 2026-11-03) with
#: ``<color|mono|primitive>/amenity.<subtree>[.<leaf>]`` icons — sparse
#: per-leaf coverage coalesces to the subtree ROOT icon
#: (``mono/amenity.<subtree>``), the generic per-subtree fallback.
#: Dedicated iconpacks (accommodation-grade) are a later pass.
#:
#: ``icon`` = frontend overlay-chip icon id (static
#: ``overlays/exports/<name>.svg``) — provisional stand-ins, swap when
#: dedicated chips land (accommodations precedent: "huts").
@dataclass(frozen=True)
class AmenityOverlaySpec:
    subtree: str
    name: str
    description: str
    #: Backend icon-library reference (``pack/slug@mono``) — the
    #: frontend resolves it via GET /v1/icons (fluent-emoji carries a
    #: mono style per icon).
    icon: str
    min_zoom: int
    cluster_max_zoom: int
    max_label_zoom: int
    order: int


AMENITY_OVERLAYS: dict[str, AmenityOverlaySpec] = {
    # ── tier A: accommodation parity ──
    "restaurant": AmenityOverlaySpec(
        subtree="restaurant",
        name="Restaurants",
        description=(
            "Restaurants, cafés and bars from the POI database "
            "(geoplaces vector tiles, server-clustered, MLT via Martin)."
        ),
        icon="fluent-emoji/fork-and-knife@mono",
        min_zoom=5,
        cluster_max_zoom=7,
        max_label_zoom=11,
        order=12,
    ),
    "health_and_emergency": AmenityOverlaySpec(
        subtree="health_and_emergency",
        name="Health & emergency",
        description=(
            "Doctors, pharmacies and emergency services from the POI "
            "database (geoplaces vector tiles, server-clustered, MLT "
            "via Martin)."
        ),
        icon="fluent-emoji/hospital@mono",
        min_zoom=5,
        cluster_max_zoom=7,
        max_label_zoom=11,
        order=13,
    ),
    "outdoor_services": AmenityOverlaySpec(
        subtree="outdoor_services",
        name="Outdoor services",
        description=(
            "Bike rental and repair, showers and other outdoor services "
            "from the POI database (geoplaces vector tiles, "
            "server-clustered, MLT via Martin)."
        ),
        icon="fluent-emoji/camping@mono",
        min_zoom=5,
        cluster_max_zoom=7,
        max_label_zoom=11,
        order=14,
    ),
    # ── tier B: mid importance ──
    "groceries": AmenityOverlaySpec(
        subtree="groceries",
        name="Groceries",
        description=(
            "Supermarkets, bakeries and other food shops from the POI "
            "database (geoplaces vector tiles, server-clustered, MLT "
            "via Martin)."
        ),
        icon="fluent-emoji/shopping-cart@mono",
        min_zoom=9,
        cluster_max_zoom=9,
        max_label_zoom=11,
        order=15,
    ),
    "shopping": AmenityOverlaySpec(
        subtree="shopping",
        name="Shopping",
        description=(
            "Shops and retail from the POI database (geoplaces vector "
            "tiles, server-clustered, MLT via Martin)."
        ),
        icon="fluent-emoji/shopping-bags@mono",
        min_zoom=9,
        cluster_max_zoom=9,
        max_label_zoom=11,
        order=16,
    ),
    "tourism": AmenityOverlaySpec(
        subtree="tourism",
        name="Tourism",
        description=(
            "Attractions, museums and viewpoints from the POI database "
            "(geoplaces vector tiles, server-clustered, MLT via Martin)."
        ),
        icon="fluent-emoji/castle@mono",
        min_zoom=9,
        cluster_max_zoom=9,
        max_label_zoom=11,
        order=17,
    ),
    "services": AmenityOverlaySpec(
        subtree="services",
        name="Services",
        description=(
            "Hairdressers, repairs and other everyday services from the "
            "POI database (geoplaces vector tiles, server-clustered, "
            "MLT via Martin)."
        ),
        icon="fluent-emoji/hammer-and-wrench@mono",
        min_zoom=9,
        cluster_max_zoom=9,
        max_label_zoom=11,
        order=18,
    ),
    "finance": AmenityOverlaySpec(
        subtree="finance",
        name="Finance",
        description=(
            "Banks and ATMs from the POI database (geoplaces vector "
            "tiles, server-clustered, MLT via Martin)."
        ),
        icon="fluent-emoji/bank@mono",
        min_zoom=9,
        cluster_max_zoom=9,
        max_label_zoom=11,
        order=19,
    ),
    # ── tier C: low importance, close-up only ──
    "utilities": AmenityOverlaySpec(
        subtree="utilities",
        name="Utilities",
        description=(
            "Toilets, drinking water and fire pits from the POI database "
            "(geoplaces vector tiles, visible when zoomed in close, MLT "
            "via Martin)."
        ),
        icon="fluent-emoji/toilet@mono",
        min_zoom=13,
        cluster_max_zoom=11,
        max_label_zoom=13,
        order=20,
    ),
    "automotive": AmenityOverlaySpec(
        subtree="automotive",
        name="Automotive",
        description=(
            "Parking, fuel and charging from the POI database (geoplaces "
            "vector tiles, visible when zoomed in close, MLT via "
            "Martin)."
        ),
        icon="fluent-emoji/automobile@mono",
        min_zoom=13,
        cluster_max_zoom=11,
        max_label_zoom=13,
        order=21,
    ),
}

#: Absolute zoom ladders shared with the accommodations overlay — a
#: marker is the same size at the same zoom whatever the overlay's
#: floor (MapLibre clamps below the first stop).


def amenity_overlay_style(spec: AmenityOverlaySpec) -> dict[str, Any]:
    """The geoplaces overlay document for one amenity subtree.

    The accommodations overlay's visual grammar (see
    :func:`accommodations_style`), parameterized by the subtree's
    importance band: ``min_zoom`` (source + layers + catalog floor),
    ``cluster_max_zoom`` (server clustering ceiling; the icon ladder
    flips mono-first at its transition-zone end, ``cmz + 2``) and
    ``max_label_zoom`` (names ride the tiles from there). No
    ``icon_scale`` parameter — the ladder is baked (see
    ``_work/261103_amenity_overlays.md``).
    """
    subtree = spec.subtree
    source_id = f"wd-{subtree}"
    sprite_id = f"wd-sdf-{subtree}"
    fallback = f"{sprite_id}:mono/amenity.{subtree}"
    raw_floor = spec.cluster_max_zoom + 2
    count_filter: list[Any] = ["==", ["get", "count"], 1]
    cluster_filter: list[Any] = [">", ["get", "count"], 1]

    def ladder(stops: list[tuple[int, float]]) -> list[Any]:
        flat: list[Any] = []
        for zoom, size in stops:
            flat.extend((zoom, size))
        return ["interpolate", ["linear"], ["zoom"], *flat]

    icon_ladder = [
        "step",
        ["zoom"],
        [
            "coalesce",
            [
                "image",
                [
                    "concat",
                    f"{sprite_id}:primitive/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", fallback],
            [
                "image",
                [
                    "concat",
                    f"{sprite_id}:mono/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", fallback],
        ],
        raw_floor,
        [
            "coalesce",
            [
                "image",
                [
                    "concat",
                    f"{sprite_id}:mono/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", fallback],
            [
                "image",
                [
                    "concat",
                    f"{sprite_id}:primitive/amenity.",
                    ["get", "category_identifier"],
                ],
            ],
            ["image", fallback],
        ],
    ]

    return {
        "version": 8,
        "name": subtree,
        "sources": {
            source_id: {
                "type": "vector",
                # Same contract as wd-accommodations: inline MLT tiles
                # with the subtree filter; maxzoom 14 — symbols re-place
                # from z14 ancestors on deeper zooms.
                "tiles": [
                    (
                        "{{env:MARTIN_TILE_URL}}/geoplaces/{z}/{x}/{y}.mlt"
                        f"?category_tree={subtree}"
                        "&fields=color,parent_color,parent_slug,"
                        "category_identifier,importance,count,name,slug,"
                        "elevation"
                        f"&max_label_zoom={spec.max_label_zoom}"
                        f"&cluster_max_zoom={spec.cluster_max_zoom}"
                        "&cache_ttl_days=1"
                    )
                ],
                "encoding": "mlt",
                "minzoom": spec.min_zoom,
                "maxzoom": 14,
                "promoteId": "slug",
            },
        },
        "sprite": [
            {
                "id": sprite_id,
                "url": f"{{{{env:MARTIN_TILE_URL}}}}/sdf_sprite/{subtree}",
            }
        ],
        "glyphs": GLYPHS,
        "layers": [
            {
                # Server-side clusters (count>1): the SAME per-kind icon
                # as individuals — no count labels, slightly bigger with
                # member count (1.1× at 2 → 1.8× at ≥ 12; membership
                # comes from GET /v1/geoplaces/near on click) until the
                # raw icons graduate at cmz+2 (+1 for the z10+ style
                # flip).
                "id": f"{source_id}-clusters",
                "type": "symbol",
                "source": source_id,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": spec.min_zoom,
                "filter": cluster_filter,
                "layout": {
                    "icon-image": icon_ladder,
                    "icon-size": [
                        "*",
                        ladder(_AMENITY_ICON_SIZE_STOPS),
                        _CLUSTER_COUNT_SCALE,
                    ],
                    "icon-allow-overlap": True,
                    "icon-overlap": "always",
                    "symbol-sort-key": ["get", "importance"],
                },
                "paint": {
                    "icon-color": ["coalesce", ["get", "color"], "#718096"],
                    "icon-halo-color": "#ffffff",
                    "icon-halo-width": 1.5,
                    "icon-halo-blur": 0,
                    "icon-opacity": 0.85,
                },
            },
            {
                # Selection halo (app-driven feature-state, same shape as
                # wd-accommodations-selected).
                "id": f"{source_id}-selected",
                "type": "circle",
                "source": source_id,
                "source-layer": GEOPLACES_SOURCE,
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
                "id": source_id,
                "type": "symbol",
                "source": source_id,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": spec.min_zoom,
                "filter": count_filter,
                "layout": {
                    # Raw places only (count==1); names are '' server-side
                    # below max_label_zoom so the text simply never
                    # renders there.
                    "text-field": ["get", "name"],
                    "text-size": ladder(_AMENITY_TEXT_SIZE_STOPS),
                    "text-font": ["Barlow Semi Condensed SemiBold", "Noto Sans Bold"],
                    "text-anchor": "bottom",
                    "icon-allow-overlap": True,
                    "text-allow-overlap": False,
                    "symbol-sort-key": ["get", "importance"],
                    "icon-overlap": "always",
                    "text-overlap": "never",
                    "text-optional": True,
                    "icon-image": icon_ladder,
                    "icon-size": ladder(_AMENITY_ICON_SIZE_STOPS),
                    "visibility": "visible",
                },
                "paint": {
                    # SDF runtime tinting: category color from the tiles,
                    # white border around it (huts parity).
                    "icon-color": ["coalesce", ["get", "color"], "#718096"],
                    "icon-halo-color": "#ffffff",
                    "icon-halo-width": ladder(_AMENITY_HALO_STOPS),
                    "icon-halo-blur": 0,
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
                    "text-opacity": ["step", ["zoom"], 0, spec.max_label_zoom, 1],
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
                f"{source_id}-clusters",
                f"{source_id}-selected",
                source_id,
            ],
        },
    }


def amenity_overlay_style_subset(spec: AmenityOverlaySpec) -> dict[str, Any]:
    """Build the subset twin of an amenity overlay (Leaflet).

    Same surgery as the accommodations twin (:func:
    `_accommodations_style_subset`): cluster nodes as the STATIC
    fallback sprite at ~1.35× the raw icon size (count-independent —
    the whitelist has no ``*`` to scale by count), the raw symbol as
    the same static sprite — no count labels, no text, no
    feature-state selection circle.
    """
    subtree = spec.subtree
    source_id = f"wd-{subtree}"
    sprite_id = f"wd-sdf-{subtree}"
    fallback = f"{sprite_id}:mono/amenity.{subtree}"
    count_filter: list[Any] = ["==", ["get", "count"], 1]
    cluster_filter: list[Any] = [">", ["get", "count"], 1]

    def ladder(stops: list[tuple[int, float]]) -> list[Any]:
        flat: list[Any] = []
        for zoom, size in stops:
            flat.extend((zoom, size))
        return ["interpolate", ["linear"], ["zoom"], *flat]

    full = amenity_overlay_style(spec)
    return {
        "version": 8,
        "name": subtree,
        "sources": {
            source_id: {
                key: value
                for key, value in full["sources"][source_id].items()
                if key != "promoteId"
            }
        },
        "sprite": deepcopy(full["sprite"]),
        "glyphs": GLYPHS,
        "layers": [
            {
                # Cluster icons (count-independent here — the subset
                # whitelist has no ``*`` to scale by count; ~1.35× the
                # raw size at every zoom).
                "id": f"{source_id}-clusters",
                "type": "symbol",
                "source": source_id,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": spec.min_zoom,
                "filter": cluster_filter,
                "layout": {
                    "icon-image": fallback,
                    "icon-size": ladder(_AMENITY_CLUSTER_ICON_SIZE_STOPS),
                    "icon-allow-overlap": True,
                },
                "paint": {
                    "icon-color": [
                        "case",
                        ["has", "color"],
                        ["get", "color"],
                        "#718096",
                    ],
                    "icon-opacity": 0.85,
                },
            },
            {
                "id": source_id,
                "type": "symbol",
                "source": source_id,
                "source-layer": GEOPLACES_SOURCE,
                "minzoom": spec.min_zoom,
                "filter": count_filter,
                "layout": {
                    "icon-image": fallback,
                    "icon-size": ladder(_AMENITY_ICON_SIZE_STOPS),
                    "icon-allow-overlap": True,
                },
                "paint": {
                    "icon-color": [
                        "case",
                        ["has", "color"],
                        ["get", "color"],
                        "#718096",
                    ],
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
                },
            },
        ],
        "metadata": {"wd:slot_layers": [f"{source_id}-clusters", source_id]},
    }


#: Full overlay documents (fallback palette baked at import; the seed
#: re-uses the builders directly — huts/accommodations pattern).
AMENITY_OVERLAY_STYLES: dict[str, dict[str, Any]] = {
    spec.subtree: amenity_overlay_style(spec) for spec in AMENITY_OVERLAYS.values()
}

#: Subset twins — derived once at import so drift fails the seed gate
#: loudly (huts/accommodations pattern).
AMENITY_OVERLAY_STYLES_SUBSET: dict[str, dict[str, Any]] = {
    spec.subtree: amenity_overlay_style_subset(spec)
    for spec in AMENITY_OVERLAYS.values()
}


# ── Transport stops overlay (Transitland vector tiles via Martin) ────

#: The Martin source id (``passthrough.sources`` in
#: ``tile_server/config/martin.yaml``): Martin proxies the Transitland
#: v2 stops tileset, injects the ``apikey`` header server-side (the
#: key NEVER reaches clients — no token in any served URL), converts
#: MVT→MLT at serve time and answers with a 4-day stale-while-revalidate
#: Cache-Control. Upstream schema
#: (https://www.transit.land/documentation/vector-tiles): source-layer
#: ``stops``, z0–z14 (below z12 a shrinking stop sample — server-side
#: density control replaces the old client-side clustering), attributes
#: ``stop_name``, ``location_type`` (0 stop/platform, 1 station,
#: 2 entrance, 3 generic node, 4 boarding area) and ``route_types_basic``
#: — the basic GTFS route types served as a JSON string, e.g.
#: ``"[2, 3]"`` (rail + bus).
TRANSPORT_SOURCE_ID = "transitland_stops"

#: GTFS basic route type → ``transport`` category child — the tree the
#: legend and the filter resolve from, and the rows whose ``color`` the
#: seed bakes into the paint (see :func:`transport_style`). ALL TEN
#: basic GTFS types are covered — exactly what Transitland's
#: ``route_types_basic`` can carry (0 tram, 1 subway/metro, 2 rail,
#: 3 bus, 4 ferry, 5 cable tram, 6 aerial lift, 7 funicular,
#: 11 trolleybus, 12 monorail — extended codes like 700 arrive reduced
#: to these). This code-side table is the AUTHORITATIVE fast path (no
#: DB round-trip); ``categories.0022`` mirrors the same pairing into
#: each mode child's ``extra`` (``gtfs_route_type``) as data-side
#: documentation — parity is test-pinned. Paint priority is
#: rarest/most infrastructural mode first:
#: a multi-mode interchange reads as its most defining mode (rail >
#: tram > metro > lifts > ferry > trolleybus > bus — the spiritual
#: successor of the old BAV layer's train-before-bus rule). Category-less
#: stops (``route_types_basic`` absent or empty) fall through to the
#: neutral ``other`` color.
TRANSPORT_MODES: tuple[tuple[str, int], ...] = (
    ("rail", 2),
    ("tram", 0),
    ("metro", 1),
    ("monorail", 12),
    ("funicular", 7),
    ("gondola", 6),
    ("cablecar", 5),
    ("ferry", 4),
    ("trolleybus", 11),
    ("bus", 3),
)

#: Seed-time fallback palette (map_seed overlays the live category
#: rows' ``color`` values; this covers fresh installs before the
#: categories migration ran). "other" deliberately has no category —
#: it is the uncategorized remainder, not a legend entry.
TRANSPORT_FALLBACK_COLORS: dict[str, str] = {
    "rail": "#C60018",  # SBB red (the old layer's "Train")
    "tram": "#00838F",
    "metro": "#7B1FA2",
    "monorail": "#455A64",
    "funicular": "#795548",
    "gondola": "#D81B60",  # aerial lift
    "cablecar": "#FF8F00",  # cable tram
    "ferry": "#0079C7",  # the old layer's "Other" blue → ferry
    "trolleybus": "#9E9D24",
    "bus": "#2d327d",  # Post blue (the old layer's "Bus")
    "other": "#6D6D6C",
}


def _route_type_present(basic_type: int) -> list[Any]:
    """Boolean expression: the stop's ``route_types_basic`` JSON string
    carries the given basic GTFS type.

    Transitland serializes the sorted distinct codes comma-space
    separated (``"[2, 3]"``, ``"[3]"``, ``"[0, 2, 11]"``) — a code is
    present iff the string contains one of the four EXACT positions:
    ``"[<code>]"`` (only element), ``"[<code>, "`` (first of several),
    ``", <code>, "`` (middle) or ``", <code>]"`` (last). The
    position-delimited needles are unambiguous across ALL basic codes
    — shorter ``"[<code>"``/``", <code>"`` prefixes would make metro (1)
    false-match trolleybus (11) and monorail (12) strings.
    No regex (MapLibre has none) and no ``any``/``all`` (not in the
    subset whitelist) — a four-branch ``case`` folds the OR.
    Subset walker-safe operators only (``case``/``in``/``get``).
    """
    haystack = ["get", "route_types_basic"]
    return [
        "case",
        ["in", f"[{basic_type}]", haystack],
        True,
        ["in", f"[{basic_type}, ", haystack],
        True,
        ["in", f", {basic_type}, ", haystack],
        True,
        ["in", f", {basic_type}]", haystack],
        True,
        False,
    ]


def _transport_color_expr(colors: dict[str, str]) -> list[Any]:
    """Case chain: the stop's dominant mode color (TRANSPORT_MODES
    priority order, neutral fallback last).

    Colors arrive resolved (DB category rows ∪ fallback): the legend is
    category-driven and reads the same rows at serve time, so map and
    legend cannot drift apart at seed time.
    """
    color_expr: list[Any] = ["case"]
    for slug, basic_type in TRANSPORT_MODES:
        color_expr += [_route_type_present(basic_type), colors[slug]]
    color_expr.append(colors["other"])
    return color_expr


#: Zoom-dependent parent-station handling (owner decision 2026-10-30):
#: a stop GROUP is a parent station (``location_type`` 1, the named
#: stop area, e.g. "Liebefeld, Neuhausplatz") plus its boarding
#: platforms (``location_type`` 0, each carrying a ``parent_station``
#: link up — shown as 3 icons for 2 bus stops before this). Zoomed OUT
#: one marker per group is wanted → stations + standalone (parentless)
#: stops; zoomed IN the physical positions are wanted → platforms
#: only (the parent would sit redundantly mid-road between them).
#: Entrances (2), generic nodes (3) and boarding areas (4) never show.
#:
#: Circles (z11–z13.99): station OR standalone stop — parented
#: platforms are represented by their station at these zooms. A
#: case-folded OR (``any`` is not in the subset whitelist).
_TRANSPORT_CIRCLE_FILTER: list[Any] = [
    "case",
    ["==", ["get", "location_type"], 1],
    True,
    ["!", ["has", "parent_station"]],
    True,
    False,
]

#: Icons DETAIL band (z17+): boarding positions only. Stations
#: vanish here by design; a station modeled WITHOUT platforms (rare —
#: feeds model boarding positions explicitly) would drop out above
#: z17 — accepted, documented trade-off.
_TRANSPORT_ICON_FILTER: list[Any] = ["==", ["get", "location_type"], 0]

#: Mono sprite icons for the z14+ symbol layer (whole literal names).
#: The sprite id is UNIQUE PER LAYER on purpose (``wd-transport``, in
#: the ``wd``/``wd-sdf`` naming family): a shared id would collide on
#: the frontend — sprites are added once per id and the first URL wins,
#: so a late-arriving pack under a shared id never loads (the huts'
#: ``wd`` pack is already present at boot; the transport icons
#: silently resolved to nothing and stops vanished at z14+). A unique
#: id makes this overlay's pack load independently, no union merge
#: needed. Icon names are the category's tree path below ``map``
#: (``<domain>.<group>.<kind>`` — martin_sync derives them from the
#: live tree; transport is its own domain: ``transport.transport.*``).
#: Only modes whose category tree actually carries a symbol get their
#: own icon; everything else — the lifts (cablecar, gondola,
#: funicular), trolleybus, monorail and unmatched stops — falls back to
#: the group's own silhouette.
TRANSPORT_SPRITE_ID = "wd-transport"

TRANSPORT_ICONS: dict[str, str] = {
    "rail": "wd-transport:mono/transport.transport.rail",
    "tram": "wd-transport:mono/transport.transport.tram",
    "metro": "wd-transport:mono/transport.transport.metro",
    "ferry": "wd-transport:mono/transport.transport.ferry",
    "bus": "wd-transport:mono/transport.transport.bus",
}
TRANSPORT_ICON_FALLBACK = "wd-transport:mono/transport.transport"


def transport_style(colors: dict[str, str] | None = None) -> dict[str, Any]:
    """The transport-stops overlay style (single SUBSET-profile document).

    ``colors`` overlays :data:`TRANSPORT_FALLBACK_COLORS` (map_seed passes
    the live ``transport`` category rows' colors). One vector source —
    the Martin passthrough proxy of the Transitland stops tileset — MLT
    URL space + ``encoding: mlt`` (pairing contract: a ``.mlt`` tiles
    template always ships with the marker), z11–z14 with client-side
    overzoom beyond; nothing renders below z11 (owner decision: the
    overlay is a close-up aid, not a country-scale wash).

    THREE zoom bands over stops and stations only (``location_type``
    0/1 — entrances, generic nodes and boarding areas stay off the
    map), one icon per stop GROUP until detail zoom:

    * z11–z13.99: SMALL category-colored circles (``maxzoom`` 14 is
      exclusive — the icon bands take over exactly at z14), stations
      one notch larger than plain stops; stations + standalone stops
      only (parented platforms hide behind their station);
    * z14–z16.99: mono category icons, STILL one per stop group
      (stations + standalone — the same filter as the circles; owner
      decision 2026-10-30: neighborhood views stay decluttered);
    * z17+: platform detail — boarding positions only, the parent
      drops out exactly where its platforms take over.

    Icons come from the Martin sprite pack (``/sprite/transport``
    under the overlay's OWN sprite id ``wd-transport`` — unique per
    layer so the pack always loads, independent of sprite-id
    collisions) — per-mode where the tree has a symbol, the group's
    own ``mono/transport.transport`` silhouette for the rest.

    Deliberately subset-clean end to end (owner decision: the full
    profile gained nothing here — no feature-state, no day strips; a
    subset document is a valid full style by construction, so ONE row
    serves WebGL and fallback sessions alike). The icon-image case
    chain returns whole literal sprite names — ``concat`` is not in
    the subset whitelist. What a full-profile twin would add today:
    nothing functional (``promoteId`` was the only full-only key and
    nothing keyed features by id).
    """
    palette = {**TRANSPORT_FALLBACK_COLORS, **(colors or {})}

    icon_image: list[Any] = ["case"]
    for slug, basic_type in TRANSPORT_MODES:
        icon = TRANSPORT_ICONS.get(slug, TRANSPORT_ICON_FALLBACK)
        icon_image += [_route_type_present(basic_type), icon]
    icon_image.append(TRANSPORT_ICON_FALLBACK)

    def radius(small: float, large: float) -> list[Any]:
        # Stations (location_type 1) render one notch larger than plain
        # stops/platforms — the interchange hierarchy at a glance.
        return [
            "case",
            ["==", ["get", "location_type"], 1],
            large,
            small,
        ]

    return {
        "version": 8,
        "name": "transport-stops",
        "sources": {
            TRANSPORT_SOURCE_ID: {
                "type": "vector",
                # Inline tiles (not the TileJSON link) like wd-huts: the
                # URL self-manages no cache key and Martin's TileJSON
                # would build its own tiles list anyway. The {{env:…}}
                # token resolves to the tile-router origin at serve time.
                "tiles": [
                    "{{env:MARTIN_TILE_URL}}/"
                    + TRANSPORT_SOURCE_ID
                    + "/{z}/{x}/{y}.mlt"
                ],
                "encoding": "mlt",
                # z11 = the overlay floor (nothing renders below);
                # upstream serves to z14 — deeper zooms overzoom
                # client-side, no further requests.
                "minzoom": 11,
                "maxzoom": 14,
            },
        },
        "sprite": [
            # Martin serves the DB-synced category sprite pack under the
            # overlay's OWN id (unique per layer — see TRANSPORT_ICONS:
            # frontend sprite ids are add-once, a shared id would let a
            # first-added pack shadow this one and the icons would
            # silently resolve to nothing).
            {
                "id": TRANSPORT_SPRITE_ID,
                "url": "{{env:MARTIN_TILE_URL}}/sprite/transport",
            },
        ],
        "glyphs": GLYPHS,
        "layers": [
            {
                "id": "transport-stops",
                "type": "circle",
                "source": TRANSPORT_SOURCE_ID,
                "source-layer": "stops",
                "minzoom": 11,
                # exclusive: at z14 the mono icons take over
                "maxzoom": 14,
                # zoomed out: one marker per stop GROUP (stations +
                # standalone stops; parented platforms hide behind their
                # station — see _TRANSPORT_CIRCLE_FILTER)
                "filter": _TRANSPORT_CIRCLE_FILTER,
                "paint": {
                    "circle-color": _transport_color_expr(palette),
                    "circle-stroke-color": "#F6F6F6",
                    "circle-stroke-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        11,
                        0,
                        13,
                        1,
                    ],
                    # SMALL zoomed-out dots: z11 barely-there, z13 still
                    # modest — the icons carry the detail from z14.
                    "circle-radius": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        11,
                        radius(1.5, 2.0),
                        13,
                        radius(3.0, 4.0),
                    ],
                    "circle-opacity": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        11,
                        0.7,
                        12,
                        1,
                    ],
                },
            },
            {
                # neighborhood icon band: STILL one icon per stop group
                # (same filter as the circles) — decluttered until the
                # detail band takes over at z17 (exclusive maxzoom)
                "id": "transport-stops-icons",
                "type": "symbol",
                "source": TRANSPORT_SOURCE_ID,
                "source-layer": "stops",
                "minzoom": 14,
                "maxzoom": 17,
                "filter": _TRANSPORT_CIRCLE_FILTER,
                "layout": {
                    "icon-image": icon_image,
                    "icon-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        14,
                        0.35,
                        16,
                        0.5,
                    ],
                    "icon-allow-overlap": True,
                },
            },
            {
                # detail band: boarding positions only — the parent
                # drops out exactly where its platforms take over
                "id": "transport-stops-icons-detail",
                "type": "symbol",
                "source": TRANSPORT_SOURCE_ID,
                "source-layer": "stops",
                "minzoom": 17,
                "filter": _TRANSPORT_ICON_FILTER,
                "layout": {
                    # whole literal sprite names per mode (case chain) —
                    # concat is not subset-whitelisted; unmapped modes
                    # fall to the generic root silhouette
                    "icon-image": icon_image,
                    "icon-size": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        17,
                        0.5,
                        19,
                        0.65,
                    ],
                    "icon-allow-overlap": True,
                },
            },
        ],
    }


#: Module-level default (fallback palette) — tests import this; the
#: seed re-builds the document from the live category colors.
TRANSPORT_STYLE: dict[str, Any] = transport_style()


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
