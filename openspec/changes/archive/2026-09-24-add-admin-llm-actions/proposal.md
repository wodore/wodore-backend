## Why

The LLM translation and description-quality services (`translate_instance`,
`assess_instance`) merged in #156/#158 are only reachable via management
commands. Editors work in the Django admin — for them, filling missing
translations or finding bad descriptions currently means a terminal. The
archived change tasks explicitly deferred this: "admin translate/assess
actions (next admin PR)". Additionally, GeoPlace got translation support
but not assessment parity: 13,750 geoplaces carry descriptions, yet they
have no quality fields and their review-status enum still uses the vague,
unused `work` value.

## What Changes

- **Admin translate action** (Hut + GeoPlace): changelist bulk action for
  selected objects and a change-form button per object, calling
  `translate_instance()` — empty-only semantics, one API call per object,
  per-object results/skips reported, partial failures never abort the
  batch.
- **Admin assess action** (Hut + GeoPlace): changelist action + change-form
  button calling `assess_instance()` — scores stored, `done → rework`
  transitions applied, skips (empty/unsupported/already scored) reported.
- **Action endpoint safety**: change-form buttons hit a POST-only admin
  view with staff permission required; unconfigured `TRANSLATION_*` or
  API failures become actionable user messages, never a 500.
- **GeoPlace assessment parity**: `description_quality` +
  `description_quality_at` fields with check constraint (migration, no
  data migration needed); review status `work` → `rework` rename across
  model choices, check constraint, admin label map and the
  `ReviewStatus` schema enum (0 rows use `work` in dev data).
  `store_quality()`'s duck-typed `done → rework` transition now applies
  to geoplaces via a `ReviewStatusChoices` class attribute (Hut pattern).
- **Command relocation**: `assess_descriptions` moves from the huts app
  to the translations app (both models now) and gains `--geoplace SLUG`
  and `--model hut|geoplace` selectors, mirroring `update_translations`.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `llm-translations`: "Admin translate action (follow-up)" requirement
  extended — changelist action + change-form button on both models,
  POST-only/permission-guarded endpoint, per-object reporting.
- `description-quality`: storage and assessment extend from Hut to Hut +
  GeoPlace (fields, `work`→`rework` rename, transition); new admin assess
  action requirement; `assess_descriptions` gains geoplace selectors.

## Impact

- **Models/migrations**: `geometries` — additive quality fields +
  constraint + `review_status` AlterField/constraint regeneration
  (`work`→`rework`, 0 rows). No Hut model changes.
- **Admin**: both changelists gain actions/columns/filters; change forms
  gain buttons (object-tools style) wired to POST-only views.
- **Command**: `app assess_descriptions` unchanged name, new selectors,
  new module path.
- **Cost**: assess/translate buttons trigger one API call per object;
  piggyback scoring already covers translated huts.
- **Frontend**: `rework` badge note from #158 now also applies to place
  badges (`WdPlaceActions`).
