## 1. Models & migrations

- [x] 1.1 Create `server/apps/basemaps` app scaffolding (WEP010 phase 1 branch is the landing prerequisite — rebase/land it first)
- [x] 1.2 `MapSlot` model + seed migration (background, ways)
- [x] 1.3 `MapParameter` model (slug, kind, label_i18n/description_i18n, default scalar-or-JSON, constraints JSONB; `date` kind = ISO 8601 validation, runtime scope) + `MapLayerParameter` through (default override)
- [x] 1.4 `MapLayer` model: slug, spec (low|medium|high), unique (slug, spec), role, i18n fields, icon/badge refs, slot FK, order/visibility, zoom bounds, style JSONB XOR style_url (check constraint), config JSONB, interaction JSONB, sprites JSONB, coverage FK + fallback_min_zoom, basemap extras (anchors, preview, is_default, fallback self-FK)
- [x] 1.5 `MapLayerCategory` through (category FK, use, order) + `attributions` M2M to Organization + `license` FK
- [x] 1.6 Style/parameter validation: thin pydantic structural check (version==8, sources/layers shape), token allowlist from linked parameters (unknown token → error), opacity-curve validation (ascending stops, 0–1), attribution-required check for external sources
- [x] 1.7 Unfold admin: layer curation (inline parameters/categories/attributions, per-variant editing), slot/parameter admin; TABS registration in `server/settings/components/unfold.py`

## 2. Resolution & serving engine

- [x] 2.1 Parameter token resolver: JSON walk replacing `"{{slug}}"` nodes with defaults ∪ overrides (server-side core, reused by contract tests)
- [x] 2.2 Env substitution from Django settings/infisical (server-side, both modes; never a parameter)
- [x] 2.3 URL absolutization: root-relative sprite/glyph/tile refs → absolute tile-server origin; `{TILE_SERVER_URL}` placeholder support
- [x] 2.4 Variant selection: spec= exact → nearest → single-existing, with served-spec reporting

## 3. API

- [x] 3.1 `GET /v1/map/catalog` controller (lang, role filters; light metadata; parameter schemas; category minimal projections; coverage bboxes; style URLs for big styles; ETag folding content hash + lang + registry state; Cache-Control; name= + operation_id per repo invariants)
- [x] 3.2 `GET /v1/map/styles/{slug}.json` controller (resolved default; `mode=tokenized`; `spec=`; `v=` from updated_at; ETag; binary/JSON response per dmr patterns)
- [x] 3.3 Register controllers, regenerate API snapshot, add contract tests (shapes, ETag behavior, both modes, variant fallback, defensive category resolution)
- [x] 3.4 Verify no `VersionChange` needed (additive) — registry_check passes

## 4. Seed & parity

- [x] 4.1 Port style fixtures: move `tile_server/styles/*.json` into app fixtures; hand-port the 11 overlay styles + basemap definitions from the frontend factories (rasters incl. swisstopo WMTS + waymarkedtrails XYZ, huts vector + availability geojson with `{{date}}`, external style_urls)
- [x] 4.2 Author parameter set: shared opacity knobs + per-layer opacity-curve widgets + `{{date}}` runtime param
- [x] 4.3 `map_seed` command: slots, parameters, org/license links, overlays, basemaps (variants: swisstopo-light high/low), default groups; idempotent, report-only-on-change
- [x] 4.4 Parity test: resolved `wd-outdoor-base-mtk` ≡ Martin-served file modulo absolutized URLs; no-root-relative-URL assertion across all served styles

## 5. Martin cutover

- [x] 5.1 `martin_sync`: drop `_sync_styles`, drop styles path from martin.yaml generation (deploy order documented: seed before cutover)
- [x] 5.2 Update AGENTS.md/docs (tile_server/styles removal, new catalog/style endpoints)

## 6. Verification

- [x] 6.1 Unit tests: resolver (tokens, env, absolutization, variant fallback), model constraints (style XOR, unique slug+spec, unknown token, attribution required)
- [x] 6.2 Contract tests + API snapshot committed
- [x] 6.3 `inv tests` (lane runner: `scripts/lane-run.sh .venv/bin/pytest`) green
