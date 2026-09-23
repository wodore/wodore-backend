## 1. Model & migration

- [ ] 1.1 Rename `work` → `rework` ("needs rework") in `Hut._ReviewStatusChoices`; update the admin status color map entry; migration regenerates `review_status_valid` (no data migration — zero rows use `work`)
- [ ] 1.2 Add `description_quality` (`PositiveSmallIntegerField`, null, blank, check-constrained to 1–10 or NULL) and `description_quality_at` (`DateTimeField`, null, blank); additive migration
- [ ] 1.3 Add `TRANSLATION_QUALITY_REVIEW_THRESHOLD` setting (default 5) via `config()`

## 2. Client & rubric

- [ ] 2.1 Shared anchored-rubric constant in `llm.py` (1–2 unusable · 3–4 too thin/marketing-only · 5–6 adequate · 7–8 good · 9–10 excellent); assessment prompt variant reusing the Swiss-domain system prompt (rubric task + `{"score": int, "summary": str}` output contract), temperature 0
- [ ] 2.2 `TranslationClient.assess(text, context)` — parse/validate score bounds and summary length (≤300 chars), raise `TranslationError` on malformed output
- [ ] 2.3 Extend the translation response contract with optional `source_quality` (parsed when present, never fatal to translations when absent)

## 3. Service (`server.apps.translations`)

- [ ] 3.1 `store_quality(hut, score, summary, review_below)`: writes both fields, writes the `[LLM <date> · quality <n>/10]` block into `review_comment` (replace-own-previous-block policy, human text untouched), applies the `done → rework` transition per the policy matrix
- [ ] 3.2 `assess_instance(hut, client, rescore=False, review_below=None)`: skips empty descriptions and already-scored huts unless `rescore`; one call per hut; saves with `update_fields`
- [ ] 3.3 Piggyback in `translate_instance()`: when the description is non-empty and unscored, request `source_quality` in the same call and store it via `store_quality` (respect `rescore`/threshold semantics)

## 4. Command

- [ ] 4.1 `app assess_descriptions`: `--hut SLUG`, `--all`, `--limit`, `--rescore`, `--review-below N`; per-hut output (`slug: 7/10 — summary`), run summary, per-hut error isolation (same patterns as `update_translations`)

## 5. Admin (fold into the admin PR)

- [ ] 5.1 Color-coded `description_quality` column (green ≥7 / yellow 4–6 / red ≤3, grey unscored) + score-range `list_filter` on the Hut changelist; `rework` flows through the existing status filter automatically
- [ ] 5.2 Optional single-hut "assess description" admin action reusing `assess_instance`

## 6. Tests

- [ ] 6.1 Client: rubric prompt assertions, `assess()` parsing (bounds, length, malformed), `source_quality` tolerance in translation responses
- [ ] 6.2 Service: transition matrix (`done`→`rework` below threshold; `new`/`review`/`rework`/`reject` untouched), comment replace-own policy (human text preserved), piggyback on/off/skip rules, empty-description skip
- [ ] 6.3 Command: selectors, `--rescore`, `--review-below`, `--limit`, error isolation
- [ ] 6.4 Model: constraint bounds (0 and 11 rejected, NULL allowed)

## 7. Rollout

- [ ] 7.1 Deploy migration; add `rework` to frontend badge color/text maps (`WdHutToolbar`, `WdPlaceActions` fallback covers the gap meanwhile)
- [ ] 7.2 `app assess_descriptions --all --limit 10` → spot-check summaries against the rubric → tune `--review-below` → corpus run
- [ ] 7.3 Archive this change once editors have worked the first `rework` batch
