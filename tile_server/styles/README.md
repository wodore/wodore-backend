# MapLibre styles served by Martin

Everything in **this directory** (top level, `*.json`) is copied by
`martin_sync` to the Martin mount and served at
`{WODORE_TILE_SERVER_URL}/style/{filename-stem}`.

| File                       | Style id              | Purpose                                                                                                                                                           |
| -------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wd-outdoor-base-mtk.json` | `wd-outdoor-base-mtk` | **Default outdoor basemap** — Wodore fork of the Maptoolkit hiking style (Maptoolkit Community License: attribution + logo required, no pre-fetch/offline/print). |
| `wd-outdoor-base-ofm.json` | `wd-outdoor-base-ofm` | Keyless OpenFreeMap outdoor fallback (unrestricted — auto-selected when Maptoolkit tiles fail; right choice for any future offline/print feature).                |
| `huts.json`                | `huts`                | Hut overlay style (app-rendered on top of the basemap).                                                                                                           |
| `wd-terrain-test.json`     | `wd-terrain-test`     | Server-side terrain A/B test style: Martin-postprocessed contours (Mapterhorn upstream, `convert_to_contour`) + hillshade stub, no basemap. For perf comparison with the client-side plugin. |

## `src/` — upstream sources (NOT served)

The subdirectory is deliberately **not** synced: `martin_sync` globs only
top-level `*.json`. These files are kept for provenance and regeneration:

- `mtk-outdoor-src.json` — raw upstream Maptoolkit hiking style
  (`tiles.maptoolkit.org`). The served `wd-outdoor-base-mtk.json` is a
  heavily transformed fork of this (settlement dots, SAC trail styling,
  peak triangles, rivers, hillshade, typography — see the
  `wodore-frontend-quasar` PR #202 history for the transform record).
- `ofm-liberty-src.json` — vendored OpenFreeMap Liberty source
  (BSD-licensed fork of OSM Liberty,
  https://github.com/hyperknot/openfreemap-styles). The served
  `wd-outdoor-base-ofm.json` is the Wodore outdoor restyle of it.

**Editing styles:** edit the served `wd-outdoor-base-*.json` directly
(prettier-formatted JSON, validated in CI). Bump `STYLE_VERSION` in
`wodore-frontend-quasar/src/stores/map/basemap-store.ts` so browsers
re-fetch the style.
