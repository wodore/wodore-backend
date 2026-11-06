# Proposal: tile-asset-versioning

## Why

Map styles moved to the backend (`basemaps`), but their **inner asset links
are unversioned while being cached long**: Martin answers sprite and font
requests with `Cache-Control: public, max-age=604800` (7 days, no
revalidation), so an icon redesign that flows through `martin_sync` reaches
clients only after every browser (and the prod edge cache) ages its copy out
— up to 7 days. Raster tiles already solve this manually (`?v=2` /
`?v=3` in the fixtures); sprites, glyphs and Martin vector tiles have no
equivalent.

Two latent bugs make even a manual fix unreliable:

1. The style endpoint's ETag hashes `len(body)` instead of the body content
   (`api.py` `etag_source`) — an equal-length URL change would keep the ETag
   identical and clients would 304 forever on the old body.
2. The rendered-style cache key embeds only `layer.modified`
   (`_style_cache_key`) — any serve-time URL rewrite that does not touch the
   layer row would keep serving the stale rendered body.

Separately, `Category` is not `TimeStampedModel`, so in-place category edits
(color, order) bump neither the catalog version aggregate (documented
limitation in `catalog_version()`) nor any tile-data version — yet category
fields are baked into the `huts_for_tiles` view (live JOIN) and into legend
rendering.

## What Changes

- **Asset version registry** (`TileAssetVersion` model in `basemaps`):
  content versions for tile-server assets, published by observation or
  verification, plus per-URL entries for external assets.
- **Serve-time `?v=` injection**: when serving a style
  (`/v1/map/styles/{slug}.json`), append `?v=<version>` to sprite URLs,
  the glyphs URL template, and versioned Martin tile URL templates —
  Martin-origin and registry-listed external URLs only; URLs that already
  carry a query string or runtime tokens are never touched.
- **Bugfixes**: ETag hashes the body content; the rendered-style cache key
  folds in the asset-version digest.
- **Martin asset watcher** (`martin_asset_watch`): a django-q2 recurring
  task that probes Martin's actually-served sprite/font bytes and publishes
  the observed hash. Probes carry a per-run nonce query parameter so any
  edge `proxy_cache` in front of Martin is bypassed; font stacks are
  enumerated from the authored styles' `text-font` arrays (Martin serves
  glyphs under font internal names, not file names), and SDF sprite
  endpoints are probed alongside the regular ones. Publication is
  content-gated: the version changes only when Martin's served bytes
  change, so the sync→restart window can never publish a version for
  bytes Martin is not serving yet. `martin_sync` additionally enqueues
  one immediate run after a sync with changes.
- **Versioned vector tile sources** (opt-in registry): the huts overlay
  source switches from the TileJSON link to an inline `tiles` array
  (minzoom 5 / maxzoom 16 — z5 is the full-country overlay floor) so
  `?v=` can reach the tile URLs; its version is computed from cheap
  aggregates (max(modified) + count) over the view's complete dependency
  set (huts, categories, owners, organizations **and the
  hut↔organization association through-table** that feeds the `sources`
  property). With the URL now content-keyed, the huts source
  cache-control rises from 1 hour to 7 days (same class as the raster
  facades); the bump activates only via `martin_sync` + restart, which
  by deploy ordering lands after injection is already live. Availability
  stays unversioned by design (already rotates via `?date=` + short
  TTL). Geoplaces is deliberately not registered — no served style
  references it; the mechanism extends to it once one does.
- **`Category` becomes `TimeStampedModel`** (created/modified, backfilled),
  shown read-only in the admin like the symbols models — fixing the
  catalog-version limitation and feeding the huts tile version.
- **External asset verifier** (`external_asset_verify`): daily django-q2
  task doing conditional GETs (If-None-Match / If-Modified-Since, falling
  back to body hashing) on external sprite/glyph/style URLs referenced by
  active layers, bumping their registry entries on change.

## Impact

- Affected apps: `basemaps` (registry, injection, ETag/cache-key, watcher,
  verifier), `categories` (timestamps + admin), `huts` (martin_sync hook,
  seed_lib huts source inlining), `tile_server/config/martin.yaml`
  (cache_control bump).
- No API contract break: response bodies gain a query parameter on asset
  URLs inside style documents (additive); the style documents themselves
  keep the revalidate-always contract. No `Api-Version` bump.
- Ops: two django-q2 schedules are created by migration (asset watcher
  every 15 min, external verifier daily). No burginfra changes required —
  new query strings are new edge cache keys by default nginx semantics.
- Frontend: no changes required; MapLibre preserves query strings when
  appending `.json`/`.png`/`@2x` sprite suffixes (`normalizeSpriteURL`
  appends to the pathname).
