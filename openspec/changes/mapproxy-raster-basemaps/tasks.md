## 1. Models & migrations (PR A)

- [ ] 1.1 Scaffold `server/apps/basemaps` (apps.py, ready(), register in
      INSTALLED_APPS following the geometries app layout)
- [ ] 1.2 `MapCoverage`: unique `slug`, `name`, PostGIS `geometry`
      (MultiPolygon), `provenance` note; GeoJSON FeatureCollection
      property for export + migration
- [ ] 1.3 `MapSource`: unique `slug`, `name`, `kind`
      (`raster_xyz`/`raster_wms`, choices extensible), `url_template`,
      `wms_layers`/`wms_format` (nullable, validated for wms kind),
      `format` (png/jpeg/webp), `tile_size` (256/512), `min_zoom`/
      `max_zoom`, non-empty `attribution`, nullable `coverage` FK,
      `is_active`; model-level placeholder validation per kind + migration
- [ ] 1.4 `MapproxyLayer`: unique `slug` (public XYZ segment), `title`,
      `format`, `resampling` (default bilinear), `seed_min_zoom`/
      `seed_max_zoom` (nullable), `is_active` + migration
- [ ] 1.5 `MapproxyLayerSource` through model: `layer` FK, `source` FK,
      positive `order` (0 = bottom), nullable `coverage_override` FK;
      `UniqueConstraint(layer, source)`, `Index(layer, order)` + migration
- [ ] 1.6 Invariant validation: active layer must have ≥ 1 active source;
      clean `__str__`s and help texts (licensing notes on attribution)

## 2. Sync command (PR A)

- [ ] 2.1 `basemap_sync --target ./tile_sync/mapproxy --only --dry-run`
      (`@register_command(group="Maps")`): build config dicts (services
      demo+tms nw origin, grid GLOBAL_WEBMERCATOR, cache-level merged
      sources in through-model order, per-source coverage with clip, seed
      levels/bbox) and emit via `yaml.safe_dump(sort_keys=False)` under a
      GENERATED header
- [ ] 2.2 Coverage export to `coverages/<slug>.geojson` for every
      coverage referenced by synced sources/recipe entries
- [ ] 2.3 Atomic writes (temp + `os.replace`), `.manifest.json` with
      stable config hash (hash of canonical dict, not file bytes),
      counts, timestamp
- [ ] 2.4 Validation + error reporting (missing placeholders, sourceless
      active layers, wms fields missing) aborting before replacement;
      inactive objects excluded; `--only <slug>` limits rendering

## 3. Pilot parity seed (PR A)

- [ ] 3.1 Bundle Natural Earth 10m `at-boundary.geojson` and
      `ch-boundary.geojson` (CH+LI) as app fixtures (copy from the
      frontend prototype `docker/mapproxy-eu-topo/`)
- [ ] 3.2 `basemap_seed`: idempotently create the three sources, two
      coverages, and the `europe_topo` recipe in pilot order (OTM → AT →
      CH/LI); report no-op on re-run
- [ ] 3.3 Golden-file test: seed → sync renders config referencing
      exactly the pilot URLs/order/coverages

## 4. Admin (PR A)

- [ ] 4.1 `MapCoverage` admin with embedded map editing (precedent:
      geometries tilemap admin template), provenance note field
- [ ] 4.2 `MapSource` admin with kind-conditional fields (wms vs xyz),
      coverage FK, attribution help text
- [ ] 4.3 `MapproxyLayer` admin with ordered inline sources
      (drag-orderable), seed fields, and a read-only public XYZ URL
      display
- [ ] 4.4 Admin action/dry-run hint linking to the sync command for the
      current selection

## 5. Tests & CI (PR A)

- [ ] 5.1 Model validation tests (placeholders, attribution required,
      wms fields, sourceless layer invariant)
- [ ] 5.2 Sync tests: idempotency (byte-identical), dry-run touches
      nothing, atomic failure leaves old files, manifest hash stability,
      `--only` scoping, inactive exclusion
- [ ] 5.3 Seed idempotency test; full seed→sync round trip
- [ ] 5.4 CI green (lint, migrations check, pytest)

## 6. burginfra cutover (PR B, burginfra repo)

- [ ] 6.1 Replace the `wd-mapproxy` ConfigMap (yaml + 2 geojsons) with
      the shared `wd-tile-sync` PVC mounted at `/mapproxy/config` (cache
      PVC stays nested at `cache_data/`)
- [ ] 6.2 Backend deployment mounts the same PVC (writer path, e.g.
      `/mnt/tile-sync`), staging overlay only
- [ ] 6.3 Ops runbook in the app README: run `basemap_sync --target
      /mnt/tile-sync/mapproxy` → diff `.manifest.json` hash →
      `kubectl rollout restart deployment/wd-mapproxy`; rollback = redeploy
      previous config via re-sync from a DB branch/backup
- [ ] 6.4 Follow-ups (not in this change): seed Job/CronJob for
      `mapproxy-seed`, automated rollout-restart hook, production wiring
