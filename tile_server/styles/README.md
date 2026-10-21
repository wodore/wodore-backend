# tile_server styles

**Styles are no longer served by Martin.** Since WEP010 phase 2 the
backend owns them: authored styles live in
`server/apps/basemaps/fixtures/styles/` and are served by the API from
the basemaps registry at `/v1/map/styles/<slug>.json` (seed with
`app map_seed`). `martin_sync` copies tiles/sprites/fonts only.

## `src/` — upstream sources (kept for provenance, NOT served)

The subdirectory is deliberately unsynced and unreferenced; these
files are kept for provenance and regeneration:

- `mtk-outdoor-src.json` — raw upstream Maptoolkit hiking style
  (`tiles.maptoolkit.org`). `wd-outdoor-base-mtk*.json` is a heavily
  transformed fork of this (settlement dots, SAC trail styling, peak
  triangles, rivers, hillshade, typography — see the
  `wodore-frontend-quasar` PR #202 history for the transform record).
- `ofm-liberty-src.json` — vendored OpenFreeMap Liberty source
  (BSD-licensed fork of OSM Liberty,
  https://github.com/hyperknot/openfreemap-styles). `wd-outdoor-base-ofm*.json`
  is the Wodore outdoor restyle of it.

**Editing styles:** edit
`server/apps/basemaps/fixtures/styles/<slug>.json` (prettier-formatted
JSON, validated in CI) and re-run `app map_seed`.
