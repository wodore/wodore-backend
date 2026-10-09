## Why

The "Europe Topo" raster basemap (OpenTopoMap fallback + basemap.at for
Austria + swisstopo for Switzerland/Liechtenstein, border-clipped into one
merged tile layer) currently exists twice as static config: a docker-compose
prototype in the frontend repo (`wodore-frontend-quasar` @
`feat/europe-topo-basemap`, `docker/mapproxy-eu-topo/`) and a hardcoded
ConfigMap pilot in burginfra (#178). Neither is editable, reviewable, or
reusable: changing a clip polygon, adding a country, or adding a new merged
raster layer (satellite, contours) means editing YAML in git and touching
infra. WEP010 makes the backend the single source of truth for basemap
definitions — vector already flows through Martin (`martin_sync`), raster
now gets the same: database models rendered into MapProxy config by a sync
command.

## What Changes

- New `basemaps` Django app with three phase-1 models:
  `MapCoverage` (PostGIS clip polygons with provenance), `MapSource`
  (upstream raster tile/WMS source: URL template, zoom bounds, format,
  required attribution, optional clip coverage), and `MapproxyLayer` (an
  ordered cache-level merge recipe — the unit MapProxy serves as one XYZ
  layer) with the `MapproxyLayerSource` through model (order, per-entry
  coverage override).
- New `basemap_sync` management command (Martin `martin_sync` pattern):
  renders `mapproxy.yaml`, `seed.yaml`, and `coverages/*.geojson` into a
  target directory (locally `tile_sync/mapproxy/`, in-cluster the shared
  sync PVC); idempotent, atomic writes, `--dry-run`, `--only <slug>`, and
  a `.manifest.json` carrying the rendered-config hash.
- New `basemap_seed` command provisioning the current "Europe Topo"
  definition (the three sources plus Natural Earth AT / CH+LI boundary
  coverages, bundled as fixtures) so backend-generated config is
  behaviorally identical to the burginfra ConfigMap pilot — the cutover
  changes the delivery mechanism, not the tiles.
- Django admin curation: coverage geometry edited on an embedded map,
  ordered inline source lists, attribution/licensing surfaced (only
  cache-legal sources: swisstopo OGD, basemap.at CC BY 4.0,
  OpenTopoMap CC-BY-SA).
- burginfra (companion PR): switch the `wd-mapproxy` staging pilot from
  ConfigMap to the backend-synced PVC and document the ops flow
  (MapProxy reads config at startup → `rollout restart` after sync).

## Capabilities

### New Capabilities

- `raster-basemaps`: database-defined raster basemap sources, clip
  coverages, and MapProxy merge recipes with deterministic config sync.

### Postponed (explicitly NOT part of this change)

The basemap layer model (`MapLayer`: role `basemap|overlay`, raster source
or vector style reference), the user-facing basemap composition
(`Basemap`: ordered layer sets such as "vector base below z10 + raster
topo above"), vector style models (`VectorStyle`), and the frontend
basemap catalog API (`GET /v1/basemaps`) are deferred to a WEP010
follow-up change once the `MapLayer` shapes have settled. Phase 1 is
constrained to keep that door open: `MapSource.kind` uses generic values
(`raster_xyz`, `raster_wms`, with `vector_martin` reserved), no
MapProxy-specific naming leaks into `MapSource`, and layer slugs are
stable public URL segments — the postponed models can reference phase-1
rows without data migration.
