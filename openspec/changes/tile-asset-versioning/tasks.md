# Tasks: tile-asset-versioning

## 1. Foundation (category timestamps, registry model)

- [x] 1.1 `Category` → `TimeStampedModel` (`server.core.models`): add
      `created`/`modified`; `makemigrations` generates the columns **and
      the django-pgtrigger UPDATE trigger** (`pgtrigger_upd_mod_*`, same
      as every other TimeStamped table — verify it lands in the
      migration); migration backfills existing rows with `timezone.now()`;
      check MRO of `ComputedFieldsModel` + `TimeStampedModel`
- [x] 1.2 `CategoryAdmin.readonly_fields` gains `"created", "modified"`
      (symbols-admin convention)
- [x] 1.3 `TileAssetVersion` model in `basemaps`: `key` (unique slug),
      `version` (char, short hash), `origin` (`martin_sync` | `external`),
      nullable `etag`, `last_modified`, `last_checked` (validators),
      `TimeStampedModel`; registered read-only in the admin (manual edits
      only for `external` bumps) + migration
- [x] 1.4 Tests: category in-place/bulk edit bumps `catalog_version()`
      and the huts aggregate (trigger-verified); registry model
      constraints

## 2. Asset-version source of truth

- [x] 2.1 `server/apps/basemaps/tile_assets.py`: `asset_versions() ->
      dict` — merges `TileAssetVersion` rows with computed tile-source
      versions (`VERSIONED_TILE_SOURCES` deps → `max(modified)+count`
      aggregates), memoized 60 s via the Django cache; version-digest
      helper for cache keys
- [x] 2.2 `VERSIONED_TILE_SOURCES` registry — **huts only** (geoplaces
      deferred until a served style references it): deps
      `huts.Hut`, `categories.Category`, `owners.Owner`,
      `organizations.Organization`, **`huts.HutOrganizationAssociation`**
      (the through-table feeding the `sources` property); unit test parses
      `HutsForTilesView.ViewMeta.query()` SQL and asserts every referenced
      table is covered by the deps list
- [x] 2.3 Martin watcher: `martin_asset_watch` management command (thin
      wrapper around a callable in `tile_assets.py` — q2 schedules need
      dotted callables): collect sprite URLs (incl. `/sdf_sprite/`) from
      active layers' authored styles; font stacks from the styles'
      `text-font` arrays; fetch via `urllib` (timeout bounded) with a
      **per-run nonce query parameter** (`_wd_watch=<random>`) so edge
      proxy caches are bypassed; hash served bytes, publish on diff; log
      + count, never raise on probe failure
- [x] 2.4 `martin_sync` enqueues one async watcher run after a sync with
      changes; idempotent, dry-run-safe
- [x] 2.5 Data migration creating the two django-q2 `Schedule` rows
      (watcher every 15 min, verifier daily) pointing at the dotted
      callables; idempotent `get_or_create` by `func`
- [x] 2.6 Tests: watcher publishes on byte change / stays silent on
      identical bytes or probe failure (mocked fetches); nonce present on
      probe URLs; aggregate changes on FK + association edits;
      memoization window

## 3. Serve-time injection + caching bugfixes

- [x] 3.1 `inject_asset_versions(style, versions)` (in
      `basemaps/tile_assets.py`): walk `sprite[]`, `glyphs`,
      `sources[*].tiles[]`; append `?v=`; **skip only** URLs that already
      contain a query string (`?`) or `{{double-brace}}` parameter tokens
      — single-brace MapLibre tokens (`{z}`, `{fontstack}`, `{range}`)
      are preserved as part of the template; match Martin-origin
      sprite/glyph URLs, registered source-name tile paths, external
      registry prefixes; pure function, no I/O
- [x] 3.2 `get_map_style`: inject after `resolve_style` in resolved AND
      tokenized modes; `_style_cache_key` folds in the version digest
      (load-bearing); `etag_source` hashes body content (`sha256(body)`) —
      keep strong-ETag + revalidate-always contract otherwise
- [x] 3.3 Ensure `_inject_serving_metadata` still runs post-injection
      (body hash covers injected URLs; `wd:version` metadata unchanged)
- [x] 3.4 Tests: injected URLs carry `?v=` when versions published;
      unversioned when registry empty (back-compat); equal-length version
      swap changes the ETag; style cache key rotation on version change;
      availability `?date=` URL never touched; glyph `{fontstack}`
      templates still inject (single-brace tokens are not a skip reason);
      MapLibre-compat note (sprite `?v=` + suffix ordering is
      path-based)
- [x] 3.5 Update existing basemaps tests that pin sprite/glyph URL shapes

## 4. Versioned tile sources + Martin config

- [x] 4.1 `seed_lib.py` huts overlay source: TileJSON `url` → inline
      `tiles: ["{TILE_SERVER_URL}/huts/{z}/{x}/{y}"]` with
      `minzoom: 5` / `maxzoom: 16` on the source (z5 is the
      full-country overlay floor — a source minzoom of 7 would hide huts
      at z5–6); `promoteId` unchanged
- [x] 4.2 `tile_server/config/martin.yaml`: huts table source
      `cache_control: public, max-age=604800` (comment updated: URL-keyed
      via `?v=`). Rollout-safe by ordering: the config takes effect only
      after `martin_sync` + Martin restart, which follow the deploy that
      already activated injection — no window with long-cached
      unversioned tiles. Geoplaces config untouched.
- [x] 4.3 Tests: huts source has inline tiles with minzoom 5; injection
      adds `?v=` to huts tile URLs only when the aggregate is available

## 5. External asset verifier

- [x] 5.1 `external_asset_verify` management command (thin wrapper, same
      callable pattern): collect external URLs from active layers
      (`style_url` + walked sprite/glyph/tile URLs of authored styles) ∩
      registry `external` entries; conditional GET with stored
      validators; 200 → store validator + `sha256(body)` as version;
      failure → keep; per-URL result summary
- [x] 5.2 Seed baseline `external` entries for the maptoolkit sprite and
      font endpoints referenced by the mtk fixture (data migration,
      versions empty until first verify — no injection until then)
- [x] 5.3 Admin: external entries manually bumpable (version field
      editable for `origin=external` only)
- [x] 5.4 Tests: 304 → no change; 200 with ETag → version + validator
      stored; no validators → body hash; unreferenced entries skipped;
      network error → version kept

## 6. Hardening + docs

- [x] 6.1 Work doc `_work/261021_tile_asset_versioning.md`: current-state
      evidence (live headers), design summary, rollout sequence (deploy →
      martin_sync → watcher publishes → clients rotate; cache_control
      bump rides the same martin_sync), burginfra verification note
      (confirm prod `proxy_cache_key` includes `$args` — expected nginx
      default)
- [x] 6.2 Full lane test run: `scripts/lane-run.sh .venv/bin/pytest`
- [x] 6.3 CHANGELOG: cliff-generated from the PR (no API version bump; additive style-body
      change only)
