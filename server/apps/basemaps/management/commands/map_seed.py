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
from typing import Any

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management.base import BaseCommand
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
from server.apps.external_links.models import ExternalLink
from server.apps.organizations.models import Organization

FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "styles"

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
        "slug": "bav",
        "name": "BAV",
        "attribution": "Bundesamt für Verkehr (BAV)",
        "url": "https://www.bav.admin.ch",
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
            }
        ]
    },
    "huts-availability": {
        "sections": [
            {
                "title": "Availability",
                "description": "Occupancy status per day.",
                "type": "symbol_detailed",
                "category": "availability",
            }
        ]
    },
    "transport-stops": {
        "sections": [
            {
                "title": "Transport stops",
                "type": "point",
                "items": [
                    {"label": "Train", "color": "#C60018"},
                    {"label": "Bus", "color": "#2d327d"},
                    {"label": "Other", "color": "#0079C7"},
                ],
            }
        ]
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


def _links_legend(title: str, description: str, links: list[dict[str, str]]):
    return {
        "sections": [{"title": title, "description": description, "items": []}],
        "links": links,
    }


LAYERS: list[dict[str, Any]] = [
    # ── Overlays ──────────────────────────────────────────────────────
    {
        "slug": "huts",
        "role": MapLayer.Role.overlay,
        "name": "Huts",
        "description": "Mountain huts and bivouacs with type symbols.",
        "icon": "huts",
        "slot": "ways",
        "order": 0,
        "style": lib.HUTS_STYLE,
        "parameters": {"huts.icon_scale": None},
        "attributions": [],
        "categories": [
            {"slug": "accommodation", "use": "filter"},
            {"slug": "accommodation", "use": "legend"},
        ],
        "config": {
            "filters": [
                {
                    "id": "hutTypes",
                    "label": "Accommodation types",
                    "type": "multi-select",
                    "category": "accommodation",
                    "defaultValue": [],
                    "mapLayers": ["wd-huts", "wd-huts-selected"],
                    "mapProperty": "type_standard_identifier",
                    "filterExpression": "in",
                }
            ],
        },
        "interaction": {
            "click": {"layers": ["wd-huts"], "behavior": "hut-detail", "min_zoom": 8}
        },
    },
    {
        "slug": "huts-availability",
        "role": MapLayer.Role.overlay,
        "name": "Hut availability",
        "description": "Bed availability per hut for the selected date.",
        "icon": "huts",
        "slot": "ways",
        "order": 1,
        "min_zoom": 6,
        "style": lib.AVAILABILITY_STYLE,
        "parameters": {"date": None},
        "attributions": [],
        "categories": [{"slug": "availability", "use": "legend"}],
    },
    {
        "slug": "transport-stops",
        "role": MapLayer.Role.overlay,
        "name": "Public transport stops",
        "description": "Train, bus and other stops (BAV list).",
        "icon": "transport",
        "slot": "ways",
        "order": 2,
        "style": lib.TRANSPORT_STYLE,
        "attributions": ["bav", "openstreetmap"],
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
        "parameters": {"sheepdogs.opacity": None},
        "attributions": ["bafu", "swisstopo"],
    },
    # ── Basemaps ──────────────────────────────────────────────────────
    {
        "slug": "wd-outdoor-base-mtk",
        "role": MapLayer.Role.basemap,
        "name": "Wodore Outdoor",
        "description": "Outdoor basemap (Maptoolkit-based fork).",
        "spec": MapLayer.Spec.high,
        "is_default": True,
        "fallback": "wd-outdoor-base-ofm",
        "anchors": {"ways": {"before": None}, "background": {"before": None}},
        "style": _fixture_style("wd-outdoor-base-mtk"),
        "attributions": ["maptoolkit"],
    },
    {
        "slug": "wd-outdoor-base-ofm",
        "role": MapLayer.Role.basemap,
        "name": "Wodore Outdoor (OpenFreeMap)",
        "description": "Keyless outdoor basemap fallback (OpenFreeMap).",
        "spec": MapLayer.Spec.high,
        "style": _fixture_style("wd-outdoor-base-ofm"),
        "attributions": ["openfreemap"],
    },
    {
        "slug": "ch-swisstopo-light",
        "role": MapLayer.Role.basemap,
        "name": "Swiss light basemap",
        "description": "swisstopo vector light basemap.",
        "spec": MapLayer.Spec.high,
        "show": False,
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
        "coverage": "ch",
        "fallback_min_zoom": 7,
        "style": lib.swisstopo_pixelkarte_style(),
        "attributions": ["swisstopo"],
    },
    {
        "slug": "maptiler-hybrid",
        "role": MapLayer.Role.basemap,
        "name": "Satellite hybrid",
        "description": "MapTiler satellite hybrid.",
        "spec": MapLayer.Spec.high,
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
        "style_url": "https://tiles.openfreemap.org/styles/liberty",
        "attributions": ["openfreemap"],
    },
]


class Command(BaseCommand):
    """Provision the map layer catalog (idempotent)."""

    help = "Seed map slots, parameters, layers and links (frontend parity)."

    def handle(self, *args: Any, **options: Any) -> None:
        created = updated = 0

        slots = self._seed_slots()
        params = self._seed_parameters()
        orgs = self._seed_orgs()
        coverage = self._seed_coverage()

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
            "config": parent.get("config"),
            "interaction": parent.get("interaction"),
            "coverage": coverage if parent.get("coverage") == "ch" else None,
            "fallback_min_zoom": parent.get("fallback_min_zoom"),
            "anchors": variant.get("anchors", parent.get("anchors")),
            "legend": self._seed_legend(parent["slug"]),
        }

        layer, was_created = MapLayer.objects.update_or_create(
            slug=slug, spec=spec, defaults=defaults
        )
        changed = int(not was_created)  # update_or_create reports nothing finer

        if parent.get("fallback"):
            fallback = MapLayer.objects.filter(slug=parent["fallback"]).first()
            if fallback and layer.fallback != fallback:
                layer.fallback = fallback
                layer.save(update_fields=["fallback"])

        self._sync_parameters(layer, parent, params)
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
        self, layer: MapLayer, parent: dict[str, Any], params: dict[str, MapParameter]
    ) -> None:
        wanted = parent.get("parameters", {})
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
