## ADDED Requirements

### Requirement: Raster source registry

The system SHALL maintain upstream raster sources (`MapSource`) with a
unique slug, a kind (`raster_xyz` or `raster_wms`), a MapProxy-style URL
template (tile sources: `%(z)s`, `%(x)s`, `%(y)s` placeholders; WMS:
service URL plus layer list), a tile format, a tile size, min/max zoom
bounds, a non-empty attribution string, and an optional default
`MapCoverage` clip. `MapSource` SHALL NOT carry MapProxy-specific
semantics so the postponed layer/basemap models can reference it
unchanged.

#### Scenario: Placeholder validation

- WHEN a `raster_xyz` source is saved whose URL template is missing any of
  `%(z)s`, `%(x)s`, `%(y)s`
- THEN the save is rejected with a validation error naming the missing
  placeholders

#### Scenario: Attribution is mandatory

- WHEN a source is saved with an empty attribution
- THEN the save is rejected (only license-compatible, attributable sources
  may be cached: swisstopo OGD, basemap.at CC BY 4.0, OpenTopoMap
  CC-BY-SA)

### Requirement: Clip coverage registry

The system SHALL maintain clip polygons (`MapCoverage`) as PostGIS
multipolygons with a unique slug, a human-readable name, and a provenance
note (e.g. "Natural Earth 10m, public domain"). `basemap_sync` SHALL
export every coverage referenced by an active recipe or source as a GeoJSON
FeatureCollection file `coverages/<slug>.geojson` next to the rendered
config.

#### Scenario: Boundary upgrade without config edits

- WHEN a curator replaces the CH+LI coverage geometry with
  swissBOUNDARIES3D data in the admin
- THEN the next sync exports the new polygon and the rendered config
  references the same `coverages/ch-boundary.geojson` path, with the
  config hash changing accordingly

### Requirement: Ordered merge recipes

The system SHALL maintain MapProxy merge recipes (`MapproxyLayer`) with a
unique slug (stable public URL segment of the served XYZ layer), a title,
a cache format, resampling, seed zoom bounds, and an ordered, non-empty
list of active sources through `MapproxyLayerSource` (`order`, 0 =
bottom). Each entry MAY override the clip coverage for that source within
the recipe. Inactive sources or layers SHALL be excluded from sync. The
source order SHALL map directly to the MapProxy cache `sources` list
(left = bottom … right = top) — cache-level merge, never layer-level.

#### Scenario: Country merge order

- WHEN `europe_topo` orders OpenTopoMap (0), basemap.at (1), swisstopo
  (2), with basemap.at clipped to the AT polygon and swisstopo clipped to
  the CH+LI polygon
- THEN the rendered cache lists the sources in exactly that order and
  renders national styles inside each clip, OpenTopoMap everywhere else

#### Scenario: Per-recipe clip override

- WHEN a recipe entry sets a `coverage_override` different from the
  source's default coverage
- THEN the rendered source within that recipe uses the override, while
  other recipes using the same source keep the default

### Requirement: Deterministic config sync

The system SHALL provide `basemap_sync [--target DIR] [--only SLUG]
[--dry-run]` that renders `mapproxy.yaml`, `seed.yaml`,
`coverages/*.geojson`, and a `.manifest.json` (config hash, layer/source
counts, timestamp) into the target directory (default
`tile_sync/mapproxy/`). Re-running without model changes SHALL produce
byte-identical files. Writes SHALL be atomic (temp file + replace) and a
failed validation SHALL abort before any file is replaced. Recipes
violating invariants (no active sources, missing URL placeholders) SHALL
be reported and skipped from rendering.

#### Scenario: Idempotent re-run

- WHEN `basemap_sync` runs twice with no model changes in between
- THEN the second run reports no changes and all file hashes are identical

#### Scenario: Dry run

- WHEN `basemap_sync --dry-run` runs
- THEN the rendered artifacts are validated and reported but no files in
  the target directory are created or modified

### Requirement: Pilot parity seed

The system SHALL provide `basemap_seed` that idempotently provisions the
"Europe Topo" definition matching the burginfra #178 pilot: the three
sources (OpenTopoMap, basemap.at geolandbasemap, swisstopo pixelkarte)
with pilot URL templates, zoom bounds, and attributions; the Natural Earth
AT and CH+LI coverages bundled as app fixtures; and one `europe_topo`
`MapproxyLayer` in pilot order. Re-running SHALL update nothing and report
as much.

#### Scenario: Seed then sync equals pilot behavior

- WHEN `basemap_seed` runs on an empty database followed by `basemap_sync`
- THEN the rendered config references exactly the three pilot upstream
  URLs, the ordered cache merge, and the two clip coverages, producing the
  same tiles as the ConfigMap pilot

### Requirement: Admin curation

The Django admin SHALL support editing coverages on an embedded map
widget, reordering recipe sources inline, and editing sources/layers with
attribution and licensing help texts surfaced. Each `MapproxyLayer` SHALL
display the resulting public XYZ URL
(`/mapproxy/tiles/<slug>/webmercator/{z}/{x}/{y}.png`).

#### Scenario: Curator adds a country

- WHEN a curator creates an AT coverage-based source entry on an existing
  recipe and runs sync followed by a MapProxy rollout
- THEN the merged layer serves the new country's style at the border
  without any manual YAML or infra change
