# Tasks: geoplace-kind-fk

## 1. Model + migration

- [ ] 1.1 `GeoPlace.kind` FK (`categories.Category`, null=True,
      SET_NULL, `related_name="places_anchored"`, `kind_id`
      declaration) + Meta stays (auto FK index)
- [ ] 1.2 Migration `0073_geoplace_kind_fk`: AddField + backfill
      (first association per place by `(order, slug)`, chunked) +
      reverse (null out)
- [ ] 1.3 `kinds.py`: `anchor_category(categories)` helper (first by
      `(order, slug)` — the rule every consumer uses)

## 2. Write paths

- [ ] 2.1 `_create_from_schema` / `_update_from_schema`: derive
      `kind` + `domain` together from the spec list; protection key
      `"kind"` alongside `"domain"`
- [ ] 2.2 OSM bulk path: `kind_id` in the bulk_update fields
- [ ] 2.3 Wodore import: verify via the schema path (no extra work
      expected — test pins it)

## 3. API

- [ ] 3.1 `anchor_kinds_for` reads `place.kind_id` (single indexed
      query; keep the association fallback for pre-backfill rows in
      the same transaction window)
- [ ] 3.2 `kind_ref_for` gains `classifier` + `extra` from the
      anchor association
- [ ] 3.3 `build_categories_data` excludes the anchor kind row
- [ ] 3.4 `kind` filter: direct FK join
      (`kind__identifier__in / kind__slug__in`)
- [ ] 3.5 `CategoryKindRefSchema`: `classifier: str | None`,
      `extra: dict | None` (additive); snapshot regenerate; registry
      note (categories narrowing rides the unreleased version)

## 4. Admin + verification

- [ ] 4.1 GeoPlace admin: `kind` FK readonly replaces
      `kind_display`; fieldset pairing with `domain`
- [ ] 4.2 Tests: FK == first association after every write path
      (schema create/update, bulk, wodore); backfill correctness;
      kind member classifier/extra; categories exclude anchor; kind
      filter; lane DB migrate + spot-check
- [ ] 4.3 Full suite + pyrefly + makemigrations --check; PR
      (`type:feature`, `api:breaking` for the categories narrowing —
      unreleased, `BUILD`)
