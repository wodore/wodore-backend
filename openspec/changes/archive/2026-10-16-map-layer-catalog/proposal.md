## Why

Map overlays (11) and basemaps (~7) are hardcoded in the frontend: styles, legends, filters, opacity curves, i18n labels, and country fallbacks all live in TS factories (`src/stores/map/utils/overlays.ts`, `basemap-store.ts`). Curating them requires a frontend deploy; users cannot customize anything beyond toggles; and the vector style JSONs are served by Martin from git files (`tile_server/styles/`) that the backend cannot render dynamically. This change makes the backend the single source of truth for map layer definitions — the explicit WEP010 phase-2 follow-up ("MapLayer, role basemap|overlay, catalog API").

## What Changes

- New `basemaps` Django app with the layer registry (WEP010 phase 1, branch `docs/wep010-basemap-selfhosting`, remains the prerequisite and lands first — this change builds on its `MapCoverage`):
  - `MapLayer`: role (`basemap`|`overlay`), i18n name/description, icon + optional badge (icon library refs, flags included), slot FK, order, zoom bounds, `style` JSONB (MapLibre StyleSpecification) XOR `style_url` (externally authored styles), coverage FK + `fallback_min_zoom` (replaces the frontend's `countryOnly`/`bbox` logic), basemap `fallback` FK (mtk→ofm), sprites, interaction hints, anchors/preview for basemaps.
  - **Spec variants**: `spec` enum (`low`/`medium`/`high`), unique `(slug, spec)` — the same layer in multiple device tiers; clients pick by GPU tier with graceful fallback in both directions.
  - `MapSlot` lookup (background/ways, extensible), `MapParameter` registry with `kind`s (scalar: number/color/boolean/enum/string/date-runtime; widget: `opacity-curve` holding a whole expression as default) + i18n label/description, referenced from styles as `"{{token}}"` nodes; per-layer M2M through with default override.
  - `MapLayerCategory` through-table (levels, symbols, colors from the existing categories app) — powers filters and legends; catalog embeds a minimal stable projection.
  - Attribution reuse: M2M to `Organization` (which already carries an `attribution` field) + FK to `licenses.License` — no new attribution model.
- New API (additive, no version bump):
  - `GET /v1/map/catalog?lang=&role=` — light metadata index (labels, icons, parameters, variants, resolved category projections, coverage bounds); never inlines base styles.
  - `GET /v1/map/styles/{slug}.json?spec=&mode=&v=` — **resolved by default** (parameter defaults + server-side env substitution, absolute sprite/glyph/tile URLs): a plain MapLibre style consumable by any client; `?mode=tokenized` keeps parameter tokens for customizing clients; env is always resolved server-side (API keys live in backend config).
  - `martin_sync` drops the styles step — Martin serves tiles, sprites, fonts only; style JSONs move from `tile_server/styles/` into the registry.
- `map_seed` management command (idempotent, `basemap_seed` pattern): slots, parameters, org/license links, all current overlays and basemaps as fixture-backed rows; parity test against today's Martin-served styles.

## Capabilities

### New Capabilities

- `map-layer-catalog`: the layer registry — models, spec variants, parameters (variables + widgets), category/attribution links, seed and parity.
- `map-style-api`: catalog + style endpoints — resolution modes, URL absolutization, env handling, caching/ETag, martin_sync reduction.

### Modified Capabilities

(none — no existing spec's requirements change)

## Impact

- **Backend**: new app `server/apps/basemaps` (on top of WEP010 ph1); `server/apps/huts/management/commands/martin_sync.py` loses `_sync_styles`; new controllers under `/v1/map/`; admin (Unfold) curation; migrations; `tile_server/styles/` content becomes fixtures.
- **API**: additive endpoints — no `VersionChange`, but snapshot + contract tests required per repo API rules; ETag keys on content hash + lang.
- **Frontend** (follow-up lane, separate repo): catalog loader replaces the TS factories; token resolution + settings-tab rendering of parameters; GPU-tier variant selection; localStorage stays until the preferences lane.
- **Deferred** (explicitly out of scope): user map-preferences API (`/v1/me/map-preferences`), custom user layers (`UserMapLayer` + `/v1/me/map-layers`), basemap zoom-compositions, mapproxy-recipes-as-overlay-source, og:image unification.
