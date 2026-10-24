# Tasks: geoplace-capacity-and-types-via-categories

## 1. Vocabulary & model semantics

- [ ] 1.1 Data migration creating the `season` parent category with
      children `winter_room`, `self_service`, `year_round`, `closed`,
      `summer_only` (active, ordered, slug-stable; idempotent rerun)
- [ ] 1.2 Update `GeoPlaceCategory` help texts; add `clean()` validation:
      classifier must have parent slug `season`; `capacity_open`/
      `capacity_closed` in `extra` must be non-negative ints when present
- [ ] 1.3 Unit tests for the association validation (valid classifier,
      wrong-subtree classifier, bad capacities, unknown keys preserved)

## 2. Schema path & import rewrite

- [ ] 2.1 Extend the geoplace input schema with per-category
      `classifier` (identifier) and `extra`; teach
      `GeoPlace.update_or_create`/`_create_from_schema`/
      `_update_from_schema` to write them on the association — invoking
      the same validation as `clean()` (classifier season-subtree check,
      capacity type/range check), since Django does not call `clean()` on
      these paths
- [ ] 2.2 Rewrite the wodore handler in `import_geoplaces` onto the
      schema path: base fields + `hut_type_open` → category,
      `hut_type_closed` → season classifier (design mapping),
      `capacity_open`/`capacity_closed` → `extra`
- [ ] 2.3 Import tests: full-field hut, hut without closed type /
      capacities, re-run with `--update` respects protected fields
      (factory-based; no network)

## 3. API & admin

- [ ] 3.1 Extend `CategoryPlaceTypeSchema` with `classifier` and `extra`;
      populate in search/nearby/amenity-detail handlers under the
      `fields[places]` sparse-fieldset selection; register the additive
      API change in the API changelog per `api-conventions`; schema +
      response tests
- [ ] 3.2 Add the `classifier` identifier to the categories JSON of the
      `geoplaces_for_tiles` view (next to the existing `extra`); view test
      asserting both
- [ ] 3.3 `GeoPlaceCategoryInline` (already renders an unscoped
      `classifier` autocomplete): scope the autocomplete to `season.*`,
      render the capacity keys as labeled numeric fields writing into
      `extra`, and wire the formset save to mark the place `is_modified`
      plus record the association attributes in `protected_fields`
      (associations carry no automatic tracking); admin test for all three
- [ ] 3.4 Fix the pre-existing `AttributeError` in `get_amenity`
      (`AmenityDetail` has no `websites`/`extra` fields): serve links from
      the external-link associations and overflow data from
      `GeoPlace.extra`, or drop the keys; response test

## 4. Backfill & verification

- [ ] 4.1 Lane-DB dry-run of `import_geoplaces -s wodore --update`,
      then real run; spot-check hut slugs for category/classifier/extra
- [ ] 4.2 Full test suite (`scripts/lane-run.sh .venv/bin/pytest`) and
      work doc under `_work/`
