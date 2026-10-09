---
draft: false
date:
  created: 2026-10-09
  updated: 2026-10-09
slug: wep010
categories:
  - WEP
  - maps
tags:
  - wep010
  - basemap
  - mapproxy
  - martin
  - tiles
---

# `WEP 10` Basemap Self-Hosting (Raster & Vector)

The platform serves its own vector tiles (Martin, fed by `martin_sync`)
but raster basemaps were either third-party or a static prototype. This
proposal makes the **backend the single source of truth for basemap
definitions** — raster and vector — with a Martin-style sync from database
to tile servers.

## Vision

| Concern | Server | Definition lives in |
|---|---|---|
| Vector tiles (huts, geoplaces, POIs) | Martin | DB views + `martin_sync` (exists) |
| Vector basemap styles (wd-outdoor family) | Martin | `tile_server/styles` (git) → DB later |
| Merged/clipped raster layers (topo, satellite, contours) | MapProxy | DB → `basemap_sync` (this WEP) |
| What the user picks ("basemap", overlays) | — | `Basemap`/`MapLayer` models (postponed) |

Phase 1 (this WEP, openspec change `mapproxy-raster-basemaps`): models
`MapSource`, `MapCoverage`, `MapproxyLayer` + `basemap_sync` /
`basemap_seed` commands + admin curation, cutting the burginfra
`wd-mapproxy` pilot over from ConfigMap to backend-synced config.

## Merge example: Europe Topo

    OpenTopoMap (worldwide fallback, bottom)
            ▲ clipped to the Austria polygon
    basemap.at geolandbasemap (AT)
            ▲ clipped to the Switzerland+Liechtenstein polygon
    swisstopo pixelkarte (CH+LI, top)
            = one merged XYZ tile layer, cuts follow actual borders

Served at `/mapproxy/tiles/europe_topo/webmercator/{z}/{x}/{y}.png`
(cache-level merge — MapProxy 7.0 only merges multiple sources at the
cache level; verified in the frontend prototype). Only license-compatible
sources are cached: swisstopo OGD, basemap.at CC BY 4.0, OpenTopoMap
CC-BY-SA.

## Postponed to a follow-up change

The `MapLayer` model (role `basemap|overlay`, raster source or vector
style reference), `Basemap` compositions (e.g. "vector base below z10 +
raster topo above"), `VectorStyle` models, and the frontend basemap
catalog API (`GET /v1/basemaps`) need more design thought — overlays and
basemaps are the same thing at the style level and differ only in role.
Phase 1 keeps the schema open for them (generic `MapSource.kind`, stable
slugs, no MapProxy semantics on sources).

## Status

- Openspec change: `openspec/changes/mapproxy-raster-basemaps/`
- Infra pilot: burginfra #178 (`wd-mapproxy`, staging)
- Prototype & source matrix: `wodore-frontend-quasar` @
  `feat/europe-topo-basemap`, `docker/mapproxy-eu-topo/README.md`
