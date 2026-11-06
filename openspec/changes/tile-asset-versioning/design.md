# Design: tile-asset-versioning

## Context

The map stack serves styles from Django (`basemaps`) with a revalidate-always
contract (strong ETag, `max-age=0, must-revalidate, stale-if-error`) — style
*documents* propagate on the next reload. The assets they link do not:

- Martin answers `/sprite/*`, `/sdf_sprite/*`, `/font/*` with
  `Cache-Control: public, max-age=604800` and no validator — sprite/font
  changes are invisible to browsers (and the prod edge nginx `proxy_cache`)
  for up to 7 days. The URLs in authored styles are unversioned.
- Vector tiles: the huts table source is configured `cache_control:
  public, max-age=3600` in `tile_server/config/martin.yaml` (hourly
  revalidation traffic; edits visible up to an hour late). The geoplaces
  function source serves `max-age=86400` and self-caches in
  `geometries_tile_cache` keyed by `(z, x, y, md5(query_params +
  cache_version))` with TTL expiry. Availability rotates daily via `?date=`
  and self-caches with a 900 s TTL.
- Raster facades already do manual `?v=N` busting under a 7-day immutable
  router header — the proven in-repo pattern this change generalizes.

Two latent bugs block any URL-rewriting fix today: the style ETag hashes
`len(body)` (equal-length changes keep the ETag), and `_style_cache_key`
embeds only `layer.modified` (serve-time rewrites would keep hitting the
stale rendered body).

Verified client behavior: MapLibre GL JS `normalizeSpriteURL` appends
`.json`/`.png`/`@2x` to the *pathname* and preserves the query string
(frontend uses maplibre-gl ^6.14), Martin ignores unknown query parameters
on sprite/font/tile routes, and Martin forwards URL query params into
function sources (`query_params`) — which is how `?date=` already reaches
the availability function.

## Goals / Non-Goals

**Goals:**

- Sprite/font/tile changes visible to clients on the next reload after
  publication — no manual `?v=` bumps, no burginfra coupling.
- Make long cache lifetimes *safe*: unchanged version = immutable-ish
  caching all the way (browser, edge, function-side DB caches); changed
  version = every layer's key rotates at once.
- Keep the revalidate-always contract for style documents unchanged.
- Fix the ETag and render-cache-key bugs.
- Make category (and other FK) edits bump the versions that depend on them.

**Non-Goals:**

- Moving sprites/fonts off Martin (Django media). Martin compiles
  spritesheets (PNG+JSON, @2x, SDF, combined) and glyph PBF ranges on the
  fly; reimplementing that in Django buys nothing.
- Versioning availability tiles — they churn intraday and already rotate
  via `?date=` + short TTLs. Deliberately excluded (opt-in registry).
- Any burginfra change: new query strings are new nginx `proxy_cache` keys
  by default; the existing martin nginx-cache tier needs no edit.
- New API version: additive query parameters inside style documents.

## Decisions

### D1 — One registry, three kinds of entries

`TileAssetVersion` (basemaps app): `key` (unique), `version` (short hash),
`origin` (`martin_sync` | `external`), plus external validator fields
(`etag`, `last_modified`, `last_checked`) and timestamps.

- `martin_sync` entries (`sprites`, `fonts`): published by the watcher (D2).
- **Computed** entries are *not* stored — tile-source versions are derived
  at serve time from cheap DB aggregates (D4) and memoized alongside the
  registry read.
- `external` entries: keyed by URL; bumped by the verifier (D6) or manually
  in the admin.

Rationale: one lookup feeds the injector; storage only where no cheap
derivation exists.

### D2 — Publication by observation (content-gated, no restart coupling)

A recurring django-q2 task (`martin_asset_watch`, every 15 min) probes the
asset endpoints Martin actually serves — discovered from the *active
layers' authored styles*: the `sprite` entries (both `/sprite/` and
`/sdf_sprite/` URLs), and the `glyphs` template instantiated once per
font stack named in the styles' `text-font` arrays (Martin serves
glyphs under font internal names — file names would 404). Every probe
carries a per-run **nonce query parameter** (`?_wd_watch=<random>`), so
an nginx `proxy_cache` tier between Django and Martin cannot serve the
watcher stale edge bytes after a Martin restart (nginx cache keys
include the query string by default; Martin ignores unknown params).
An optional `MARTIN_INTERNAL_TILE_URL` setting may later pin the probes
to an internal origin instead — the nonce alone is deploy-neutral and
sufficient. The task hashes the served bytes (`.json` + `.png` per
sprite URL, one `0-255.pbf` per font stack) and publishes
`hash(observed bytes)` when it differs from the stored version.

- Martin not restarted yet after `martin_sync` → served bytes unchanged →
  nothing published → no poisoned version. Whenever the restart happens
  (burginfra auto-restart or manually), the next observation publishes.
  No timers, no webhooks, no timeout alerts.
- `martin_sync` additionally enqueues one async run after a sync with
  changes, so publication is usually minutes, not up to 15.
- A byproduct: a Martin upgrade that re-encodes spritesheets bumps the
  version once — harmless (identical icons under a new key).
- The watcher writes nothing on Martin downtime (probe failure = keep the
  stored version; logged, surfaced by the q2 error reporter).

### D3 — Serve-time injection + the two bugfixes

Injection runs in the style-serving path (`api.get_map_style` /
`resolution.resolve_style` pipeline) as a final URL pass:

- `sprite[]` URLs and the `glyphs` template whose origin is the tile server
  get `?v=<sprites|fonts version>`.
- Tile URL templates (`sources[*].tiles[]`) whose path matches a
  registered Martin source name (see D4) get `?v=<tiles:source version>`.
- Registry-listed external URLs (by prefix match) get `?v=<external
  version>`.
- **Never** touch a URL that already contains `?`/`&` or runtime tokens
  (`{{…}}`, `{z}` absent) — self-rotating URLs (availability's
  `?date={{date}}&days=4`) manage their own freshness. Injection is
  strictly additive: no stored or authored style is rewritten.

Bugfixes in the same code path (both required for injection to work):

- ETag: `sha256(body)` replaces `len(body)` in `etag_source`.
- `_style_cache_key` additionally embeds the asset-version digest used for
  the render, so a published version change re-renders immediately.

Both keep the existing semantics otherwise (strong ETag,
revalidate-always, version-keyed body cache).

### D4 — Tile-source versioning is opt-in, per-source, FK-complete

A code-level registry (module constant, single place of policy):

```python
VERSIONED_TILE_SOURCES = {
    "huts": {
        "deps": [
            "huts.Hut",
            "categories.Category",
            "owners.Owner",
            "organizations.Organization",
        ],
    },
    "geoplaces": {"deps": ["geometries.GeoPlace", ...]},
}
```

- Version = sha256 over each dep table's `max(modified)` + `count()`,
  memoized ~60 s (same pattern as `catalog_version()`).
- The huts overlay source switches from the TileJSON link
  (`"url": "{TILE_SERVER_URL}/huts"`) to an inline `tiles` array —
  otherwise `?v=` cannot reach the tile URLs (Martin's TileJSON builds its
  own tiles list). `minzoom`/`maxzoom` move onto the source as **5/16**,
  matching the Martin table config (z5 is the full-country overlay floor —
  `OVERLAY_MIN_ZOOM`; a source minzoom of 7 would hide huts at z5–6).
- Huts deps (FK-complete, matching the view SQL):
  `huts.Hut`, `categories.Category`, `owners.Owner`,
  `organizations.Organization`, **and
  `huts.HutOrganizationAssociation`** — the through-table builds the
  `sources` property; an association edit changes served bytes and must
  rotate the version. A unit test parses `ViewMeta.query()` and asserts
  every referenced table is covered by the deps list.
- Geoplaces is **not registered** in this change: no served style
  references it, so injection would never reach its URLs (the mechanism
  is generic; when a style inlines a geoplaces source, its entry lands
  and the injected `v=` rotates the function's DB tile-cache key —
  migration 0041 computes `md5(query_params::text ||
  cache_version::text)`).
- With URLs content-keyed, `tile_server/config/martin.yaml` raises the
  huts source `cache_control` from `max-age=3600` to `max-age=604800`
  (bounded, no `immutable` — a safety net that self-heals within days in
  any pathological case). Deploy-ordering note: **`map_seed` must re-run
  before the Martin restart** — the inline-tiles huts source lives in
  `seed_lib.py`, and existing DB rows keep the TileJSON `url` (which
  `?v=` cannot reach) until re-seeded; only then does `martin_sync`
  regenerate the config (raising the cache TTL) and the restart apply
  it, with injection already live. Full sequence:
  deploy → `app map_seed` → `app martin_sync` → Martin restart →
  watcher publishes. Geoplaces keeps its existing 86400 config
  untouched.
- Availability is absent from the registry → never aggregated, never
  injected.

### D5 — `Category` becomes `TimeStampedModel`

`created`/`modified` added (backfill `now()` in the migration), fields
read-only in the admin (`readonly_fields` gains `"created", "modified"`,
matching the symbols-admin convention). This feeds both the huts tile
version (D4 deps) and `catalog_version()`, which already picks up
`modified` when the field exists — closing its documented limitation for
in-place category edits.

### D6 — External assets: daily conditional-GET verification

`external_asset_verify` (daily django-q2 task): collect external URLs from
active layers — `style_url` fields plus external sprite/glyph/tile URLs
walked out of authored style trees — intersected with existing
`external` registry entries plus a small seeded baseline (maptoolkit
sprite/font endpoints). For each: conditional GET with stored
`If-None-Match`/`If-Modified-Since`; on 200 store the new validator and
`version = sha256(body)` (no validator support → body hash every run);
on network failure keep the old version. Verification happens at most once
per day per asset, only for assets referenced by active layers.

Injection for externals appends `?v=` to their URLs in served styles —
the provider's server ignores the unknown param; browsers and CDNs treat
it as a new cache key. URLs already versioned in-path (openfreemap
`ofm_f384`) are not seeded into the registry — the path version already
rotates their cache.

## Risks / Trade-offs

- **Probe cost**: the watcher fetches a handful of small sprite/font
  responses every 15 min — negligible; Martin serves them from its
  spritesheet cache.
- **Version bump without visible change** (Martin re-encode, harmless
  hash collision on aggregate): one extra sprite fetch per client,
  self-limiting.
- **Served-hash vs source-hash**: we deliberately version *served* bytes;
  a category icon edit that compiles to identical sheet bytes would not
  bump — correct by definition (clients could not observe a difference).
- **Aggregate misses a dep table** (D4): a new JOIN added to the view
  without updating the deps list would serve stale `?v=` for that table's
  edits — mitigated by a unit test asserting the deps list against the
  view SQL's tables (parsed from `ViewMeta.query()`).
- **Race window**: an edit committing between aggregate computation and
  tile render can cache slightly-newer bytes under the old version for up
  to the memo TTL; the next memo tick bumps and rotates. Bounded by 60 s,
  strictly better than today's hourly revalidation window.
- **q2 availability**: publication and verification depend on the
  qcluster running. Failure mode is delayed publication (stale-but-correct
  version), never a wrong version — and martin_sync's immediate enqueue
  still publishes on deploy runs.
