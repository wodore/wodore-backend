# Tasks: place-detail-endpoint

## 1. Schema & response shape

- [ ] 1.1 `GeoPlaceDetailSchema` in `server/apps/geometries/schemas/
      _output.py`: `GeoPlaceBaseSchema` + `description`,
      `review_status`, `detail_type`, `amenity_detail`, `slug`
      (optional); required members `id`, `name`, `detail_type`,
      `location`, `importance`; keep the `WodoreSerializer`
      exclude-unset semantics for optional members
- [ ] 1.2 Confirm the `GeoPlaceFields` sparse-fieldset registration
      covers the endpoint (`places`, `categories`, `sources`, plus
      `parties` once `geoplace-parties` has landed)

- [ ] 1.3 Slug NOT NULL cleanup: `AlterField` on `GeoPlace.slug` to
      `null=False` (keep `blank=True` — `save()` auto-mints, forms
      stay permissive); safe — production data has 0 NULL slugs; test
      that a row without a slug is rejected at the database level

## 2. Presenter & controllers

- [ ] 2.1 Extract a shared detail presenter into
      `server/apps/geometries/presenters.py` (base fields via
      `base_result` + `description`/`review_status`/`detail_type`/
      `slug` + the `amenity_detail` block + `categories`/`sources`
      via `build_categories_data`/`annotate_sources`/`build_sources`);
      `record_visit` hook after existence is known
- [ ] 2.2 New `PlaceController` (`get_place`) at
      `places/<int:place_id>` with `name="get_place"`,
      `cache_headers(60)` + `cache_page(60)`; resolution
      `is_active=True, is_public=True`; `raise_not_found` on miss
      (no existence oracle)
- [ ] 2.3 Convert `AmenityController` into the deprecated alias: keep
      operation id/URL name `get_amenity`, delegate to the shared
      presenter with the `detail_type="amenity"` scope (non-amenity
      404 preserved), same response body and cache headers; mark
      deprecated in the OpenAPI description pointing to `get_place`
      (dmr `@modify` — check `deprecated` support, else description
      text); note the accepted `is_public` tightening in the PR body
- [ ] 2.4 `field_selected` gating for `amenity_detail` (skip
      `select_related`), `categories` (skip prefetch) and `sources`
      (skip annotation) when not selected

## 3. Projection & narrowing

- [ ] 3.1 Apply `fields[places]` narrowing on the detail response via
      dict-level `project_fields` (the `nearby` pattern): required
      members + i18n companions always kept — assumes the
      `geoplace-parties` required-fields projection fix

## 4. Tests

- [ ] 4.1 Per-detail-type coverage: amenity with block, natural/admin/
      none without; 404s (unknown, inactive, non-public — identical
      body per the single error contract); `slug` always present
      (never-null invariant)
- [ ] 4.2 Selection: default full response;
      `?fields[places]=id,name,amenity_detail` narrowing; block of
      another type absent (200, no error); unknown block name → 400
      naming valid values; nested `fields[parties]` once the parties
      change has landed; `lang` localization of `name`/`description`
- [ ] 4.3 Alias: parity with `get_place` for amenity ids, non-amenity
      404, deprecation marking, cache headers on both routes
- [ ] 4.4 Contract: regenerate the OpenAPI snapshot if the
      api-registry CI step requires; additive — assert no
      `VersionChange` is registered

## 5. Changelog & verification

- [ ] 5.1 PR labels `type:feature` + `api:added` (both changelogs per
      the `api-changelog` capability — no manual changelog entries)
- [ ] 5.2 Full lane test suite
      (`scripts/lane-run.sh .venv/bin/pytest`) and a work doc under
      `_work/`
