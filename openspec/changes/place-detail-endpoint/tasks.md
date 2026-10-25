# Tasks: place-detail-endpoint

## 1. Slug invariant & grammar (model + migration)

- [x] 1.1 `AlterField` on `GeoPlace.slug` to `null=False` (keep
      `blank=True` — `save()` auto-mints, forms stay permissive);
      safe — production data has 0 NULL slugs
- [x] 1.2 Slug grammar enforcement, two layers: (a) `CheckConstraint`
      on `GeoPlace.slug` matching the converter regex
      (`^[a-z0-9_-]*[-_][a-z0-9_-]*$`, sibling of the existing
      `detail_type_valid` constraint) — `save()` does not run
      `clean()`, so the constraint is the real guarantee; (b)
      `GeoPlace.clean_slug` mirroring it plus the reserved-name
      blacklist (`search`, `nearby`, `overlays`, `meta`, `amenity`)
      for friendly admin errors; unit tests for both layers (valid
      legacy shapes pass; pure words, uppercase, and reserved names
      rejected)
- [x] 1.3 One-time data migration: re-mint any slug violating the
      grammar (expected: none — 0 of 441,940 fail the regex on the
      dev snapshot; assert count in the migration log), then add the
      check constraint in the same migration (re-mint first,
      constraint second)

## 2. Converter & routing

- [x] 2.1 `GeoPlaceSlugConverter` (regex `[a-z0-9_-]*[-_][a-z0-9_-]*`)
      registered via `register_converter`; module home near the geo
      routing code, importable without app-loading side effects
- [x] 2.2 New route `places/<geoplace:slug>` (`name="get_place"`);
      SEO siblings switch to `places/<geoplace:slug>/meta` and
      `places/<geoplace:slug>.md`; fixed-segment rule (single
      lowercase words, no `-`/`_`) documented next to the paths list
- [x] 2.3 Remove `places/amenity/<int:place_id>` and the
      `AmenityController` (route + controller + schema exports);
      startup checks E003/E004 stay green (`name=` == operation id
      on every route)

## 3. Schemas, presenter & controllers

- [x] 3.1 Identifier swap family-wide: `GeoPlaceBaseSchema` drops
      `id`, gains required `slug`; `base_result` carries `slug`;
      search/nearby controllers updated (visit hook stays on detail)
- [x] 3.2 `GeoPlaceDetailSchema` in `schemas/_output.py`:
      required `slug`, `name`, `detail_type`, `location`,
      `importance`; optional `country_code`, `elevation`,
      `description`, `review_status`, `amenity_detail`, `categories`,
      `sources` (+ `parties` once `geoplace-parties` has landed)
- [x] 3.3 Shared detail presenter in `presenters.py` (reuse
      `base_result`, `build_categories_data`, `annotate_sources`,
      `build_sources`); resolution `is_active=True, is_public=True`;
      `raise_not_found` on miss (no existence oracle); `record_visit`
      after existence is known
- [x] 3.4 `PlaceController.get_place` with `cache_headers(60)` +
      `cache_page(60)`; `field_selected` gating for `amenity_detail`
      (skip `select_related`), `categories` (skip prefetch),
      `sources` (skip annotation)
- [x] 3.5 `fields[places]` narrowing via dict-level projection with
      required-members-keep (`_narrow_place_detail` — validates
      against declared members so block names stay valid on every
      place type; assumes the `geoplace-parties` projection fix)
      plus nested `fields[TYPE]` narrowing like `nearby`

## 4. Version registry & snapshot

- [x] 4.1 Amend the *unreleased* `VersionChange` in
      `server/apps/apiversions/registry.py`: extend the description
      with the slug-only identifier switch and the `get_amenity`
      removal (sunset window 0, zero consumers — 2026-10-02
      precedent); no downgrade transforms needed for removals
- [x] 4.2 Regenerate and commit the OpenAPI snapshot (`app
      api_snapshot`); `python3 -m server.apps.apiversions.
      registry_check` passes (no stacking)

## 5. Tests

- [x] 5.1 Routing disjointness: `/v1/geo/places/search|nearby|
      overlays` resolve to the fixed endpoints with the item route
      registered in any order; item fetch works for legacy slug
      shapes (`vending_machine`, `drinking_water-`, `information-5h9`)
- [x] 5.2 Identifier policy: search/nearby/detail responses carry
      `slug` and no `id`; old amenity path 404s from the router
- [x] 5.3 Per-detail-type coverage: amenity with block, natural/admin/
      none without; 404s (unknown, inactive, non-public — identical
      body per the single error contract incl. RFC 9457 members)
- [x] 5.4 Selection: default full response;
      `?fields[places]=slug,name,amenity_detail` narrowing; block of
      another type absent (200, no error); unknown block name → 400
      naming valid values; `lang` localization
- [x] 5.5 Caching: `Cache-Control: public, max-age=60` on the detail
      route; `lang`/`fields` variants cache separately
- [x] 5.6 Contract: snapshot matches registry; pinned-old-version
      behavior matches the amended `VersionChange` description
      (registry_check green, snapshot regenerated)

## 6. Changelog, client & verification

- [ ] 6.1 PR labels `type:feature` + `api:breaking` (both changelogs
      per the `api-changelog` capability — no manual changelog
      entries) — **applies at PR creation time**
- [ ] 6.2 Frontend: regenerate the API client (wodore_v1.d.ts) and
      drop the now-removed `get_amenity` operation from any local
      stubs (no call sites exist) — **separate repo, follow-up**
- [x] 6.3 Full lane test suite
      (`scripts/lane-run.sh .venv/bin/pytest`) and a work doc under
      `_work/`
