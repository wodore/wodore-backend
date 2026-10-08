# Why

Group icons in the frontend are picked from Iconify at runtime
(`fluent-emoji-flat:*` names): search depends on a third-party API, keyword
data is bolted on client-side (emojibase, lazy-loaded), and icon identity is
an external string we do not control. Beyond emoji, the platform needs a
home for other curated icon sets (map overlays next, future UI iconography)
— today there is no searchable, pack-organized icon registry in the backend.

For the picker the product decision is Fluent Emoji (Color / Flat / High
Contrast map to the visual modes detailed / simple / mono) with Noto Emoji
as a secondary set; both currently render via Iconify. Owning them in the
backend gives stable IDs, localized search in our four UI languages, a
browsable taxonomy, and no third-party dependency in the picker — and the
same registry serves any future pack.

## What Changes

- New **icon library** capability built on existing models wherever
  possible: assets are `Symbol` rows (runtime media uploads, review
  workflow, imagor, existing `/v1/symbols` endpoints), attribution reuses
  `License` / `Organization`, and the CLDR group/subgroup taxonomy is
  modeled as real `Category` rows (`emoji` root → groups → subgroups) with
  localized names.
- New models in the symbols app: `SymbolCollection` (a pack — same concept
  as meteo's `WeatherCodeSymbolCollection`), `Icon` (one row per icon per
  pack: `(pack, slug)` unique, i18n name, `symbol_detailed` /
  `symbol_simple` / `symbol_mono` FK slots, nullable `category` FK to the
  subgroup, `curated` flag), `IconKeyword` (localized, folded search
  index).
- Import **Fluent Emoji** (MIT) and **Noto Emoji** (Apache-2.0) at pinned
  refs as the first two packs (`fluent-emoji`, `noto-emoji`) via one
  idempotent management command. Asset rows carry pack prefixes
  (`fluent-emoji-tent`), mirroring the meteo importers (`weather-icons-*`,
  `meteoswiss-*`); `Icon` rows keep the clean upstream slug. Keywords come
  from emojibase-data (de/en/fr/it); the CLDR taxonomy is get-or-created
  with localized names. Packs are open-ended — overlays or hand-curated
  sets are just more packs, no schema or code change.
- Read-only API `GET /v1/icons`: ranked localized typo-tolerant search,
  pack / category / curated filters, per-style asset URLs via the existing
  `resolve_symbol_urls()` helper. Additive — no API version bump.
- Frontend picker (separate PR, frontend repo) switches from Iconify to
  this endpoint; stored legacy names keep rendering via Iconify as a
  transitional fallback.

## Capabilities

### New Capabilities

- `icon-library`: pack-based icon registry (models, import, taxonomy) with
  localized keywords and a searchable read API.

### Modified Capabilities

(none — additive; `Symbol` and `Category` schemas are unchanged, only
referenced)

## Impact

- **New models**: `SymbolCollection`, `Icon`, `IconKeyword` in
  `server.apps.symbols` (+ migrations)
- **Reused models**: `Symbol` (asset layer), `Category` (taxonomy),
  `License`, `Organization`, `TimeStampedModel`, modeltrans i18n
- **Import**: `import_emoji --ref <pin> [--noto-ref <pin>]`; idempotent
  upserts; records upstream refs + licenses for attribution tooling
- **API**: `GET /v1/icons` — `search`, `lang`, `pack`, `category`,
  `curated`, `limit/offset`; public read-only, cacheable
- **Out of scope**: consolidating meteo's `WeatherCodeSymbolCollection`
  onto `SymbolCollection` (follow-up change once proven); user-uploaded
  custom icons; per-user icon favorites (follow-ups once settings sync
  exists)
