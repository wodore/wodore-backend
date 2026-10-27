# Tasks: style-profiles-subset

## 1. Model: profile + version fields

- [x] 1.1 `MapLayer.profile` (`models.py`): `TextChoices` `full` |
      `subset`, default `full`, db_index; DB check constraint
      `basemaps_maplayer_profile_valid` mirroring
      `basemaps_maplayer_spec_valid`; help text ("format richness of the
      style document — subset rows are strict MapLibre subsets
      renderable by simpler engines"); admin field (editable, list
      filter) per the Unfold conventions
- [x] 1.2 `MapLayer.version` char field (max 16, blank): "rules this
      document was validated against" — style-spec release for `full`,
      subset revision for `subset`; `clean()` requires it for inline
      `style` rows, allows empty for `style_url` rows; validate the
      dotted-decimal shape
- [x] 1.3 Migration: add both columns; replace `unique_slug_spec_variant`
      with `unique_slug_spec_profile_variant` on `(slug, spec, profile)`;
      existing rows keep `profile='full'` (default) — verify the
      `style_xor_style_url` and spec/role checks are untouched
- [x] 1.4 `MapLayer.clean()`: `profile=subset` inline styles run the
      subset walker and report its errors on the `style`
      field; full rows keep today's structural checks only (depends on
      the walker — task 3.1 lands first)
- [x] 1.5 Tests: constraint rejections (duplicate `(slug, spec,
      profile)`, invalid profile value), version required-for-inline /
      optional-for-URL, subset rows rejected by `clean()` when the walker
      fails (walker fixtures shared with task 3.4)

## 2. Resolution: 2D walk + capability parameter

- [x] 2.1 `MapLayer.pick_variant(…, profile=…)`: implement the D3 walk —
      `full` clients iterate `[T, *SPEC_FALLBACKS[T]]` preferring `full`
      then `subset` per tier; `subset` clients iterate the same tier
      order, `subset` only; omitted profile stays profile-agnostic
      (today's behavior). Keep the `is_active` filter and single-variant
      fallback semantics
- [x] 2.2 Query models (`api.py`): `LayersQuery`, `MapStylesQuery` and
      the style-endpoint view gain `profile: full|subset` (optional,
      pattern-validated, description naming it a *capability*, not a
      preference); omitted = current behavior (#331 compatible)
- [x] 2.3 `resolution.style_endpoint_url(slug, spec, profile)`; payload
      `style_url` appends `profile=` **only when the request carried the
      parameter** (strict #331 byte-compat when omitted); Martin-parity
      catalog (`/v1/map/catalog`) resolves `profile` into `path` the
      same way
- [x] 2.4 `MapLayerEntry` gains `profile` (served variant) and `version`
      (served variant, null for external `style_url` rows) with field
      descriptions that clearly distinguish `version` (rules version)
      from the existing `style_version` (cache token)
- [x] 2.5 Cache correctness (mostly automatic): the layers/detail/
      slots/catalog ETags already fold the full query string
      (`etag_page` hashes the sorted params), and the style endpoint's
      rendered-body cache key is per **row** (`_style_cache_key` keys on
      `layer.pk`/`layer.spec`) — so the required change is exactly that
      `pick_variant` (including `get_map_style`, which today reads only
      `spec`) honors `profile`; verify with tests that the same slug at
      two profiles yields distinct ETags and cache entries
- [x] 2.6 Tests: resolution chains (full client tier-first
      `full@T→subset@T→full@T′`, subset client never receives full,
      omitted profile unchanged for #331 clients); payload fields;
      `style_url` profile parameter; slugs without subset variants are
      absent from `?profile=subset` collections and 404 on style/detail;
      ETag folding (same row, different `profile` → different ETag/body)

## 3. Subset validator (pure-Python walker)

- [x] 3.1 `validation.py`: subset walker (~100 lines) implementing
      subset v0.1 — whitelists as module constants (top-level keys;
      source key sets per raster/vector/geojson; layer types; layout keys
      per type; paint set incl. icon-size/text-size in either slot;
      expression operators `get/has/match/case/in/==/interpolate(zoom)/literal`
      with recursive descent and the `["linear"]`-only-inside-interpolate
      rule); path-precise error messages; `"{{slug}}"` token nodes pass
      through like values
- [x] 3.2 Wire into `MapLayer.clean()` (task 1.4) so admin edits gate —
      AND into the `map_seed` layer upsert **directly, before the
      write**: the seed uses `MapLayer.objects.update_or_create(...)`,
      which bypasses `clean()` entirely, so the upsert calls the walker
      (plus the version-required check) on the prepared defaults and
      fails the seed loudly (seed gating must be real, not CI-only)
- [x] 3.3 CI sweep: management command (or system check) running the
      walker over **every** `profile=subset` row + the seed fixtures;
      nonzero exit on any violation (catches tagging drift)
- [x] 3.4 Tests: acceptance fixtures (raster overlay as-authored,
      transport-stops-like circle/case/in/interpolate-zoom,
      match-on-property circle color, symbol icon+simple text) and
      rejection fixtures (fill layer, feature-state, non-whitelisted
      operator like `coalesce`, data-driven non-whitelisted paint,
      promoteId source key, TileJSON `url` vector source, layout
      visibility key)

## 4. Full-profile validation (styl, CI-only)

- [x] 4.1 CI job validating every inline `full` seed/fixture style with
      `styl` — a light job that installs the styl binary (one-line
      `install.sh` from github.com/navidnabavi/styl, or the GitHub
      Action `navidnabavi/styl@v0.0.4`), dumps the seed's inline styles
      to files (management command over the `map_seed` definitions — no
      DB rows needed) and runs `styl validate` (E-code spec violations)
      over the dump plus `server/apps/basemaps/fixtures/styles/`;
      `.stylrc` config committed (no Node, no server-runtime dependency)
- [x] 4.2 Record the style-spec release styl validates against as the
      seeded `version` of `full` inline rows (e.g. `26.4.4`);
      document in the field help text that `version` travels with
      re-validation

## 5. Clustering config (rendering hint)

- [x] 5.1 Structural validation for `config.clustering` at save: known
      keys (`enabled`, `source`, `groupByProperty`, `radius`, `maxZoom`,
      `bubble`), type checks, `bubble` carries either property references
      (`colorProperty`/`iconProperty`/`countProperty`) or literal
      fallbacks (`color`/`icon`); property names are free-form strings
- [x] 5.2 Seed the huts overlay's `config.clustering` block (D5 schema:
      `source: wd-huts`, `groupByProperty: type_standard_slug`,
      `radius: 48`, `maxZoom: 11`, bubble property references) alongside
      the existing `config.filters`
- [x] 5.3 Tests: the block serializes through the resolved variant row's
      `config` (payload passthrough); malformed clustering blocks are
      rejected by `clean()`; null-bucket semantics documented in the
      field help text (features lacking `groupByProperty` form one
      bucket)

## 6. One-time seed tagging

- [x] 6.1 `map_seed.py`: tag the 9 raster overlays + `world-topo` as
      `profile=subset`, `version="0.1"`; all other rows `profile=full`
      with `version` = the styl-validated style-spec release (inline
      styles) or empty (`style_url` rows) — the D6 table is the source of
      truth; data migration for deployed DBs (idempotent, converges with
      re-run `map_seed`; the seed upsert keys on `(slug, spec, profile)`
      and the migration retags in place so no orphan `full` twins
      remain — depends on the walker, task 3.1)
- [x] 6.2 Update `map_seed` idempotency tests: second run reports no
      changes (profile/version are part of the update_or_create
      defaults)
- [x] 6.3 Docs: `AGENTS.md` basemaps section gains a paragraph on
      profile/version semantics and the subset tagging convention
