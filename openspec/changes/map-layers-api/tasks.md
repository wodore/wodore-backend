# Tasks — map-layers-api

## 1. Spec resolution chain

- [ ] Replace `MapLayer.pick_variant`'s distance walk with the explicit
      `SPEC_FALLBACKS` table (`low→medium→high`, `medium→low→high`,
      `high→medium→low`; then single-variant; else `None`)
- [ ] Unit tests pinning all three chains, both-direction single-variant
      fallback, and no-variant behavior

## 2. Layers / layer-detail / slots endpoints

- [ ] `MapLayersQuery` (lang, spec, role, show) + sparse fieldset composition
      on the layer schema
- [ ] `GET /v1/map/layers` → `{"data": [resolved…], "count": N}` via a shared
      `_resolved_summary(layer, spec)` builder (served `spec`, `style_url`,
      `modified`, resolved-row fields; no `variants`, no inline styles)
- [ ] `GET /v1/map/layers/{slug}` → same object, per-layer ETag
- [ ] `GET /v1/map/slots` → `{"data": [...], "count": N}`
- [ ] Contract tests: envelope, resolution, `show`/`role` filters, sparse
      fieldsets (including 400 on unknown field names), hidden-basemap
      inclusion by default

## 3. Catalog slim-down & config removal

- [ ] `GET /v1/map/catalog` → `{"styles": {slug: {name, path}}}` with
      `?spec=` resolved into `path`; drop selector metadata
- [ ] Remove `GET /v1/map/config` and `MapConfigController`
- [ ] Amend the unreleased `VersionChange` with the downgrade transforms
      (config → layers mapping for pinned clients; catalog slimming);
      regenerate the API snapshot; keep contract tests green

## 4. Version-keyed ETag caching

- [ ] `catalog_version()` aggregate over every serialized model
      (max `modified` + counts), ≤10 s memo
- [ ] Conditional wrapper (strong ETag = version ∪ lang ∪ spec ∪ role ∪
      show ∪ fieldset ∪ api-version; manual `If-None-Match` → 304;
      version-keyed body cache) replacing `cache_page` on layers,
      layers/{slug}, slots, catalog
- [ ] Revalidate-always headers incl. `stale-if-error=604800` on all map
      endpoints and the external-style redirect; remove
      `INLINE_STYLE_MAX_BYTES` and the inline path
- [ ] Contract tests: one-reload freshness (edit → non-304), 304 on
      unchanged, ETag varies with lang/spec/role/fields

## 5. Seed & docs

- [ ] `map_seed` idempotence re-check (no row changes expected — data-driven)
- [ ] OpenAPI descriptions for the new params; note the per-spec legend
      scope in the model help text (seed keeps shared legends)

## 6. Frontend follow-up (wodore-frontend-quasar, separate PR)

- [ ] Basemap store consumes `/v1/map/layers` (picker via sparse fieldset);
      delete `fetchBasemapCatalog`, `mapBasemapCatalogCache`,
      `refreshBasemaps`, `martinCatalogBasemap`, `STYLE_VERSION`,
      client-side `pickVariant`
- [ ] Overlay store switches `version` → `modified`
- [ ] Optional: `visibilitychange` revalidate for long-lived tabs
