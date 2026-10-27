# Proposal: style-profiles-subset

## Why

The frontend ships a Leaflet-based fallback map for no-WebGL users (frontend
PRs #352, #359) that must render the same backend map-layer catalog as the
MapLibre map. Leaflet can only render a strict subset of the MapLibre style
spec — and today nothing in the catalog says which layers those are: the
frontend guesses compatibility by inspecting served styles (a fragile
heuristic) and carries hardcoded copies of palette values as a crutch.
Compatibility is an authoring fact, not a client inference — it belongs in
the backend.

The catalog's variant model currently has exactly one dimension: the device
tier `spec ∈ low|medium|high` keyed `(slug, spec)` with a tier fallback
chain. Renderer capability (full MapLibre vs Leaflet-renderable subset) is
orthogonal to device tier and needs to become a second, explicit dimension
of the same variant rows — plus a machine-checkable definition of what
"Leaflet-renderable" means, so compatibility claims are validated, not
hoped for.

## What Changes

- **`profile` field on `MapLayer` variant rows** — `full | subset`
  (default `full`). Not a 4th spec tier (renderer capability × device tier
  are orthogonal), not renderer names (a subset style does not require
  Leaflet — it is simply a strict subset of the MapLibre spec that any full
  renderer can also consume).
- **`version` field on `MapLayer` variant rows** — records *the rules this
  document was validated against*: the `@maplibre/maplibre-gl-style-spec`
  release (e.g. `26.4.4`) for `full` rows, our subset revision (e.g.
  `0.1`) for `subset` rows. The style document's internal `"version": 8`
  field is untouched.
- **Subset profile v0.1 — a strict whitelist**: raster/vector(MLT)/geojson
  sources; `raster`/`circle`/`symbol` layers (sprite-pack icon + simple
  text) with minzoom/maxzoom; a closed paint property set (circle-*, raster-,
  icon-*, text-* essentials); expressions limited to `get`, `has`, `match`,
  `case`, `in`, `==`, `interpolate` (zoom input only), `literal`.
  Explicitly out: feature-state, fill/fill-extrusion/line/heatmap layers,
  SDF text layout props, pitch/terrain/sky, non-whitelisted data-driven
  paint.
- **Capability-based resolution**: uniqueness becomes `(slug, spec,
  profile)`; the tier fallback chain (`SPEC_FALLBACKS`) becomes a 2D walk.
  Clients send their capability as `?profile=full|subset` (omitted =
  today's behavior, backward compatible with #331 clients). Full-capable
  clients walk `full@T → subset@T → full@T′ → subset@T′ …` (device tier
  respected before format richness); subset-only clients walk
  `subset@T → subset@T′ …` and never receive a `full` row. The
  one-resolved-row contract is preserved; the payload gains the resolved
  `profile` and `version` of the winning variant; `style_url` and the
  style endpoint carry the resolved profile.
- **Clustering as a layer-config rendering hint** — `config.clustering`
  (`enabled`, `source`, `groupByProperty`, `radius`, `maxZoom`, `bubble`
  with property references or literal fallbacks) on the overlay's existing
  `config` JSONB block, never inside the style document (the MapLibre spec
  permits `cluster` only on geojson sources; on a vector source it would
  break subset validity). One config serves two modes: client-side
  clustering today, precomputed DB clusters later — same properties, config
  unchanged.
- **Validation story (no Node in the server runtime)**: `full` rows are
  validated by the `styl` Rust binary (github.com/navidnabavi/styl — cargo
  install locally, GitHub Action `navidnabavi/styl@v0.0.4` in CI, config
  via `.stylrc`); `subset` rows by a pure-Python subset walker in the
  Django app (~100 lines: the whitelists above, recursive expression
  check) running at seed ingest (model validation / management command)
  and as a CI sweep.
- **One-time manual profile tagging** of the current seeded styles (no
  auto-tagging machinery): the 9 raster overlays and the `world-topo` raster
  basemap are subset-compatible today; `world-satellite-hybrid` (vector
  label stack), the `wd-outdoor-base-*` family, `mtk-outdoor`,
  `ch-swisstopo-light`, `openfreemap-liberty`, `maptiler-hybrid` and the
  huts overlay (SDF text symbols) stay `full` until `subset` variants are
  authored.
- **Migration/compat**: additive — existing rows default `profile=full`;
  consumers that send no `profile` param see today's behavior; new payload
  fields and the `?profile=` param are additive (no `Api-Version` bump).

## Impact

- Affected app: `basemaps` — `models.py` (fields, constraints,
  `pick_variant`), `resolution.py` (`style_endpoint_url`), `api.py` (query
  models, payload, cache/ETag inputs), `validation.py` (subset walker),
  `management/commands/map_seed.py` (profile/version tagging, clustering
  config). Plus one Django migration and a CI job (`styl` + walker sweep).
- No API contract break: the `?profile=` param is optional and additive;
  payloads gain `profile`/`version` fields; `style_url` gains a query
  parameter. No `Api-Version` bump; the one-resolved-row contract of #331
  is preserved.
- Frontend (out of this repo): the Leaflet fallback map switches from
  style-sniffing heuristics to `?profile=subset` + the resolved
  `profile`/`version` fields; the MapLibre map is unaffected.
- Ops: no new server-runtime dependencies (styl is CI/local-only; the
  subset walker is pure Python); the CDN treats `?profile=` as a new cache
  key by default nginx semantics, and the rendered-style cache keys fold
  it in.
