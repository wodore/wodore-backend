## Context

Raster basemaps are served by MapProxy since burginfra #178 (staging
pilot): `wd-mapproxy` runs `mapproxy:7.0.0-nginx` with a hash-suffixed
ConfigMap holding `mapproxy.yaml` plus two Natural Earth boundary GeoJSONs
(AT, CH+LI). The config merge is done at the CACHE level (MapProxy 7.0
only merges multiple sources there; layer-level multi-source merges break
service registration — verified in the frontend prototype), clipped per
country polygon, and served as one XYZ layer:

    /mapproxy/tiles/europe_topo/webmercator/{z}/{x}/{y}.png

Vector tiles already follow a database-to-server flow: `martin_sync`
writes config/sprites/styles into a directory that is mounted into the
Martin pod (PVC `wd-martin-sync-v1` at `/martin_sync`). The cluster is
single-node, so an RWO PVC is mountable by both the backend (writer) and
a tile-server pod (reader).

## Goals / Non-Goals

- Goals: basemap raster definitions live in the database with Django
  admin curation; `basemap_sync` renders MapProxy config deterministically
  (Martin-sync ergonomics); the burginfra pilot becomes config-from-backend
  without changing served tiles; schema leaves room for the postponed
  `MapLayer` / `Basemap` / `VectorStyle` / catalog-API phase.
- Non-goals: no `MapLayer`/`Basemap`/`VectorStyle` models and no frontend
  basemap catalog API (postponed follow-up); no changes to Martin config
  or its sync; no cluster-side seed automation (seed Job is a burginfra
  follow-up); no style JSON in the database; no frontend changes (the XYZ
  URL stays hardcoded until the catalog API exists).

## Decisions

### D1: New `basemaps` app — not `geometries`/`huts`

Tile-serving code is already split (`geometries`: geoplaces tiles +
mbtiles tooling; `huts`: `martin_sync`). Basemap definitions are their own
domain with no FKs into huts/geometries, and the postponed phase-2 models
belong in the same app. A dedicated `server/apps/basemaps` keeps that
cohesion and avoids growing the two existing apps in different directions.

### D2: The MapProxy unit is a merge recipe, not a flagged source

`MapSource.use_in_mapproxy: bool` was rejected: MapProxy merges sources
**in order** (cache `sources` list, left = bottom … right = top), needs a
per-recipe clip that can differ from a source's default coverage, and
needs seed policy. None of that fits a boolean. Instead `MapproxyLayer`
owns an ordered source list (`MapproxyLayerSource.order`, 0 = bottom) with
optional per-entry `coverage_override`, and carries format/resampling/
seed fields. MapProxy-specific concerns stay inside `Mapproxy*` models;
`MapSource` stays a plain description of upstream tiles.

### D3: Coverages are PostGIS rows, exported as GeoJSON files

The database row is the truth (admin-edited on a map widget, provenance +
license note attached); the GeoJSON file is a build artifact written by
`basemap_sync` into `coverages/<slug>.geojson` because MapProxy wants file
datasources. Swapping Natural Earth 10m for swissBOUNDARIES3D later is a
geometry edit, not a config edit.

### D4: Rendered from Python dicts, not string templates

`basemap_sync` builds plain dicts and emits them with `yaml.safe_dump`
(`sort_keys=False`) under a `GENERATED` header. String/HTML templates for
YAML are fragile; the config surface is small and fully typed. Generated
files carry no tutorial comments — provenance lives in the models (help
texts, coverage notes) and in this repo's history.

### D5: Sync is pull-based and dumb — like `martin_sync`

`basemap_sync --target <dir>` writes files atomically (temp + `os.replace`)
and never restarts anything (Django has no k8s rights). Ops flow:
run sync → `kubectl rollout restart deployment/wd-mapproxy` (MapProxy
reads config at startup only). `.manifest.json` records a stable hash of
the rendered config so scripts can detect no-op syncs. The single-node
cluster makes the shared RWO `wd-tile-sync` PVC writable by the backend
and readable by `wd-mapproxy`.

### D6: `basemap_seed` encodes the pilot for a behavior-neutral cutover

The burginfra pilot serves a verified, license-checked source set. The
seed command recreates exactly that (opentopo / at_geolandbasemap /
ch_pixelkarte with their URL templates, zoom bounds, attributions, Natural
Earth clip coverages bundled as app fixtures, one `europe_topo`
MapproxyLayer in pilot order). The cutover PR then only changes *delivery*
(ConfigMap → synced PVC), and a staged diff of rendered config proves tile
behavior is unchanged.

### D7: Phase-1 schema is constrained by the postponed models

`MapSource.kind` values are generic (`raster_xyz`, `raster_wms`;
`vector_martin` reserved), slugs are stable public URL segments, and no
field embeds MapProxy semantics. When the postponed `MapLayer` (role
`basemap|overlay`, raster source or vector style reference), `Basemap`
(ordered compositions), `VectorStyle`, and the `/v1/basemaps` catalog API
land, they reference phase-1 rows as-is — no data migration, no URL
breaks. Catalog URL resolution later becomes: proxy XYZ URL when a
`MapproxyLayer` wraps the source, else the direct template.

## Risks / Trade-offs

- Rendered config loses the prototype's explanatory comments → accepted;
  documentation lives in model help texts and the WEP (D4).
- `[generated → restart]` is manual → accepted for phase 1; automating
  restart/seed Jobs is a burginfra follow-up once the flow is proven.
- Two config origins during transition (ConfigMap pilot vs synced PVC) →
  mitigated by D6 parity seed and a one-PR cutover.
