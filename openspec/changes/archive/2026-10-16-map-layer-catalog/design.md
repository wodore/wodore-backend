## Context

Frontend today: `OverlaySwitchItem` (full inline MapLibre `StyleSpecification` + config: filters/settings/legend + zoom-interpolated opacity expression applied via `setPaintProperty` per layer type) and `BasemapSwitchItem` (style object or URL, `countryOnly`/`countryMinZoom`/`bbox` fallback merge, anchors). 11 overlays — huts (Martin vector + availability GeoJSON in one style), transport-stops, 5 swisstopo WMTS rasters, 3 waymarkedtrails XYZ rasters — and ~7 basemaps (Martin-hosted `wd-outdoor-base-mtk.json` = 317 KB / 135 layers + ofm fallback; external MapTiler/swisstopo/OpenFreeMap style URLs; inline country rasters). `martin_sync` copies `tile_server/styles/` verbatim (`shutil.copy2`); Martin serves them same-origin, so relative `/font/...` + `/sprite/wd-maps` refs work. WEP010 phase 1 (unmerged prerequisite) adds `MapSource`/`MapCoverage`/`MapproxyLayer` + `basemap_sync`. Availability data: `GET /v1/huts/availability/{date}.geojson`. `Organization.attribution` and `licenses.License` exist. No user-preference storage.

## Goals / Non-Goals

- Goals: layer definitions (overlays + basemaps) live in the DB with admin curation; styles served from a backend endpoint — resolved by default, tokenized on demand; per-layer customization via parameters (scalars + widget kinds); device-tier variants; category-driven filters/legends resolved server-side; attribution/license reuse; parity-seeded catalog covering every current frontend definition; Martin reduced to tiles/sprites/fonts.
- Non-Goals: user preferences API and custom user layers (separate follow-up changes); basemap zoom-compositions; mapproxy recipes as overlay sources; frontend implementation (separate repo/lane); og:image unification; parsing frontend TS for the seed.

## Decisions

### D1: One `MapLayer` model, `role` decides — not separate overlay/basemap tables

WEP010's own conclusion ("overlays and basemaps are the same thing at the style level, differing only in role"). Basemap-only extras (anchors, preview, is_default, fallback FK) and overlay-only extras (slot, config) are nullable fields on ~30 rows — acceptable sparsity for one admin, one API, one mental model. `style` XOR `style_url`: MapLibre itself is dual (style object | style URL); everything we own (rasters incl. mapproxy XYZ output, vector, geojson) is `style`; only externally-authored full styles (MapTiler, swisstopo light, OpenFreeMap) stay `style_url` — upstream freshness, keys server-side.

### D2: Spec variants — `(slug, spec)` unique, `spec ∈ {low, medium, high}`

The same logical layer can exist per device tier (e.g. swisstopo vector `high` vs OSM raster `low`). `slug` remains the identity for groups/preferences; `spec` is a variant dimension. Clients select: exact tier → nearest available → whatever exists (a low-tier device with only a `high` variant uses it, and vice versa). User override lands with the preferences lane; the catalog contract (flat list with `slug`+`spec`) supports it from day one.

### D3: Parameters unify variables and widgets

One registry (`MapParameter`: slug, kind, label_i18n, description_i18n, default, constraints) + per-layer M2M through (optional default override). Scalar kinds (`number`, `color`, `boolean`, `enum`, `string`, `date`) render as sliders/pickers/toggles; **widget kinds** (`opacity-curve` first) hold a whole expression subtree as default and render a stop editor. `date` is a formal kind (ISO 8601, runtime scope): clients refetch any source referencing it when its value changes; resolved mode substitutes the declared default. Styles reference parameters as standalone JSON token nodes `"{{slug}}"`; per-layer curves are per-layer parameters, shared knobs dedup through the registry. Parameter values resolve most-specific-wins: registry default < authored per-layer override < user global override < user per-layer override — the user levels ship with the preferences lane, but the contract is fixed here so catalog, clients, and preferences agree; server-side resolution applies the authored levels only. This replaces today's overlay-level opacity stamping (`opacityPropertiesByType` block) — authored paint wins by construction; user value edits are ordinary parameter overrides; curve *shape* edits are expert-fork territory (follow-up lane).

### D4: Style endpoint — resolved by default, tokenized opt-in, env always server-side

`GET /v1/map/styles/{slug}.json` returns a **plain, fully-resolved MapLibre style** (parameter defaults substituted, env secrets from backend config baked, sprite/glyph/tile URLs absolutized to the tile server): consumable by any client with zero machinery, hard-cached. `?mode=tokenized` keeps parameter tokens (for the customizing app; schemas ship in the catalog) — env tokens are resolved server-side in both modes because API keys live in backend config (infisical), never as user parameters. Runtime params (`{{date}}`) resolve client-side; resolved mode substitutes the declared default. `?spec=` selects the variant (D2 fallback rule). `v` ties to `updated_at` (keeps the frontend's existing cache-bust pattern); ETag folds content hash + lang + registry state.

### D5: Absolutization is a spec-level requirement

Martin serves styles verbatim today; relative refs work only same-origin. Once served from Django, every sprite/glyph URL must be absolutized to `TILE_SERVER_URL` at serve time. Parity test: seeded resolved output diffed against today's Martin-served styles modulo URL absolutization.

### D6: Categories via through-table, minimal projection in the catalog

`MapLayerCategory` (category FK, use: filter|legend|primary, order) gives DB integrity; the catalog embeds only a minimal stable projection (slug, identifier, name, symbol URLs, color) so future category `VersionChange`s can never force catalog transforms. Legend/filter *layout* stays in `config` JSONB (validated refs, defensive serve-time resolution).

### D7: Attribution and licensing reuse existing models

M2M to `Organization` (its `attribution` + `url` fields are the payload — one swisstopo row dedups across six layers) + FK to `licenses.License`. Layers referencing third-party tile sources require ≥1 attribution (validated).

### D8: Seed = per-code + fixture files, `basemap_seed` pattern

`map_seed` provisions slots, parameters, org/license links, overlays, basemaps, default groups idempotently. Big style blobs are fixture files (mtk/ofm ported from `tile_server/styles/`; overlay styles hand-ported once from the TS factories). No frontend-TS parsing. WEP010 phase 1 remains the landing prerequisite; `martin_sync` drops `_sync_styles` in the same change so no style is served twice.

### D9: Catalog stays light

`GET /v1/map/catalog?lang=&role=` carries metadata only (identity, i18n, icons, slots, parameters with schemas, variants, category projections, coverage bounds, anchors) — never inline base styles (317 KB would make it ~400 KB and re-ship per language switch). Small overlay styles may inline; big ones expose their style endpoint URL.

## Risks / Trade-offs

- Serving styles from Django adds a hop vs Martin's static files → mitigated by ETag + long cache + `v`-based busting; styles are near-static.
- Relative-URL regression (D5) is the #1 silent-breakage risk → spec scenarios + parity test.
- The catalog couples to the categories contract via embedded projections → bounded by the minimal projection (D6).
- Optional-field sparsity on `MapLayer` → accepted at this scale (D1); splits if user layers land (follow-up uses a separate `UserMapLayer` table per the advisor review).
- martin_sync change requires a coordinated deploy (styles must exist in DB before Martin stops serving them) → seed-before-cutover ordering in tasks.
