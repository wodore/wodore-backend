## 1. OpenSpec change

- [x] 1.1 Create `add-admin-llm-actions` change: proposal, design, spec deltas (MODIFIED `llm-translations` admin translate action; MODIFIED `description-quality` storage/rework/command + ADDED admin assess action), tasks; validate

## 2. GeoPlace assessment parity

- [x] 2.1 `_ReviewStatusChoices` TextChoices with class attribute `ReviewStatusChoices` (new/review/rework/done) on GeoPlace; use in `review_status` field; update check constraint (`work`→`rework`)
- [x] 2.2 Update `work` references: model choices, admin label map (`"work": "danger"` → `"rework"`), `ReviewStatus.WORK` enum in `server/apps/geometries/schemas/_input.py` (+ REWORK), `rg '"work"'` for stragglers
- [x] 2.3 Add `description_quality` + `description_quality_at` + `description_quality_valid` constraint (Hut pattern); generate + apply migration on the lane DB
- [x] 2.4 GeoPlace admin: `description_quality` column + range filter (copy Hut's `DescriptionQualityFilter`/display)

## 3. Admin actions

- [x] 3.1 `LLMAdminMixin` in `server.apps.translations` (admin_helpers): translate + assess `@admin.action`s with lazy client, per-object messages (results/skips/errors), config errors as actionable messages
- [x] 3.2 POST-only per-object button view via `get_urls` (staff + `has_change_permission`, GET → 405) redirecting back to the change form with messages
- [x] 3.3 Object-tools buttons on the Hut and GeoPlace change forms (minimal template override)
- [x] 3.4 Register mixin on `HutsAdmin` and the GeoPlace admin

## 4. Command

- [x] 4.1 Move `assess_descriptions` to `server/apps/translations/management/commands/`; add `--geoplace SLUG` + `--model hut|geoplace` selectors (mirror `update_translations`); update test patch path

## 5. Tests

- [x] 5.1 store_quality transitions GeoPlace `done → rework` (refetch pattern); new/review untouched
- [x] 5.2 translate piggyback fires for geoplaces with descriptions (assess_source True)
- [x] 5.3 command `--geoplace` selectors; cross-model selector/`--model` combinations rejected with `CommandError` (tested)
- [x] 5.4 admin actions: callable-level behavior for translate/assess (skips, errors, config message) and button view (POST works, GET 405, no-permission 403)
- [x] 5.5 full suite green on the lane DB

## 6. Gates

- [x] 6.1 ruff check + format on touched files; openspec validate passes
