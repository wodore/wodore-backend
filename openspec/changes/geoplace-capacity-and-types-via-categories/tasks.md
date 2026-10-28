# Tasks: geoplace-capacity-and-types-via-categories

> Implementation notes: Opus advisor review (pre-implementation) found
> two correctness gaps and two stale premises — incorporated below:
> (1) the update path now *refreshes* classifier/extra on existing
> associations (additive-only would have made the backfill a no-op),
> (2) the season mapping is an exhaustive table over all 14
> `HutTypeEnum` values with an explicit default, (3) task 3.4's
> `get_amenity` AttributeError no longer exists (fixed by
> `place-detail-endpoint`) — task is verify-only, (4) task 3.3's
> protection wiring already existed (`save_formset` flat `"categories"`
> entry) — task rescoped to the genuinely new admin work.

## 1. Vocabulary & model semantics

- [x] 1.1 Data migration creating the `season` parent category with
      children `winter_room`, `self_service`, `year_round`, `closed`,
      `summer_only` (active, ordered, slug-stable; idempotent rerun) —
      `0057_seed_season_vocabulary.py` (mirrors 0052 role seed;
      sets `identifier` explicitly — computedfields never fires for
      historical models, asserted by test)
- [x] 1.2 Update `GeoPlaceCategory` help texts; add `clean()` validation:
      classifier must have parent slug `season`; `capacity_open`/
      `capacity_closed` in `extra` must be non-negative ints when present
      — shared helper `validate_attributes`/`validate_extra` +
      `normalize_extra` (drops `None`-valued capacity keys)
- [x] 1.3 Unit tests for the association validation (valid classifier,
      wrong-subtree classifier, bad capacities, unknown keys preserved)

## 2. Schema path & import rewrite

- [x] 2.1 Extend the geoplace input schema with per-category
      `classifier` (identifier) and `extra`; teach
      `GeoPlace.update_or_create`/`_create_from_schema`/
      `_update_from_schema` to write them on the association — invoking
      the same validation as `clean()` (classifier season-subtree check,
      capacity type/range check), since Django does not call `clean()` on
      these paths — `PlaceTypeInput` + `_resolve_place_types`;
      **update path refreshes existing association rows** (advisor
      finding 1), capacity keys are source truth, unknown keys preserved
- [x] 2.2 Rewrite the wodore handler in `import_geoplaces` onto the
      schema path: base fields + `hut_type_open` → category,
      `hut_type_closed` → season classifier (design mapping),
      `capacity_open`/`capacity_closed` → `extra` — exhaustive
      `HutTypeEnum` mapping table (advisor finding 2); owner party keeps
      riding `merge_owner` (`_ensure_hut_party`)
- [x] 2.3 Import tests: full-field hut, hut without closed type /
      capacities, re-run with `--update` respects protected fields
      (factory-based; no network)

## 3. API & admin

- [x] 3.1 Extend `CategoryPlaceTypeSchema` with `classifier` and `extra`;
      populate in search/nearby/amenity-detail handlers under the
      `fields[places]` sparse-fieldset selection; register the additive
      API change in the API changelog per `api-conventions`; schema +
      response tests — presenter `build_categories_data` feeds all three
      endpoints (one test each direction); changelog registration = PR
      label `api:added` (no version bump — additive only)
- [x] 3.2 Add the `classifier` identifier to the categories JSON of the
      `geoplaces_for_tiles` view (next to the existing `extra`); view test
      asserting both — view SQL + `0058_tiles_view_classifier.py`
      (recreate from `ViewMeta.query()`, 0030 pattern)
- [x] 3.3 `GeoPlaceCategoryInline` (already renders an unscoped
      `classifier` autocomplete): scope the autocomplete to `season.*`,
      render the capacity keys as labeled numeric fields writing into
      `extra`, and wire the formset save to mark the place `is_modified`
      plus record the association attributes in `protected_fields`
      (associations carry no automatic tracking); admin test for all three —
      rescoped (advisor finding 4): flat protection already existed in
      `save_formset`; new = `GeoPlaceCategoryInlineForm` (capacity fields,
      shared validation, scoped autocomplete) + formset tests
- [x] 3.4 Fix the pre-existing `AttributeError` in `get_amenity`
      (`AmenityDetail` has no `websites`/`extra` fields): serve links from
      the external-link associations and overflow data from
      `GeoPlace.extra`, or drop the keys; response test — **verify-only**:
      the endpoint was removed and the presenter rewritten by
      `place-detail-endpoint` (`build_amenity_detail` reads neither
      field); no AttributeError reachable; nothing to do

## 4. Backfill & verification

- [x] 4.1 Lane-DB dry-run of `import_geoplaces -s wodore --update`,
      then real run; spot-check hut slugs for category/classifier/extra
- [ ] 4.2 Full test suite (`scripts/lane-run.sh .venv/bin/pytest`) and
      work doc under `_work/`
