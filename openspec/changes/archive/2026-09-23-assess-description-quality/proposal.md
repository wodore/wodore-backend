## Why

Hut descriptions come from external sources of very varying quality
(one-liners, marketing fluff, outdated details). With 1'000+ huts marked
`done`, editors have no way to find the texts worth rewriting — quality
is invisible until someone reads each description. An LLM can score the
main-language description (anchored 1–10) and feed the existing review
workflow, producing a concrete worklist: "everything below 5 needs a
human". Empty descriptions are a structural gap (`update_translations`
era), not a quality problem — they are skipped, never scored 0.

## What Changes

- **Quality fields on Hut**: `description_quality` (1–10, `NULL` =
  never assessed; check-constrained) and `description_quality_at`
  (assessment timestamp). GeoPlace later if wanted.
- **Rubric-based assessment**: `TranslationClient.assess()` scores the
  `main_language` description against a fixed, anchored rubric and
  returns `{score, summary}`; the rationale is stored as a marked block
  in the existing `review_comment` (never overwriting human text).
- **Review workflow integration** — no new parallel state: the unused
  `work` status is renamed to **`rework`** ("needs rework"; 0 rows
  affected). Assessment below a threshold (default 5) moves `done` huts
  to `rework`; huts already in `new`/`review` keep their status (already
  queued) and `reject` is never touched.
- **Combined with translation**: when `update_translations` already
  calls the API for a hut, the same call also returns `source_quality`
  — zero extra requests. A standalone `assess_descriptions` command
  covers huts that need no translations (the majority) and rescoring.
- **Admin surfacing**: `rework` appears in existing status
  filters/badges automatically; a color-coded quality column and
  score-range filter join the Hut changelist (with the admin PR).

## Capabilities

### New Capabilities

- `description-quality`: quality score storage and semantics on Hut,
  anchored-rubric assessment, review-workflow integration (incl. the
  `work` → `rework` rename), combined translation-time assessment, and
  the `assess_descriptions` command.

### Modified Capabilities

(none — `llm-translations` stays as specified in
`add-main-language-translations`; the translation call merely gains an
optional response field, specified from the quality side here)

## Impact

- **Models/migrations**: `huts` — rename choice `work`→`rework`
  (regenerates `review_status_valid` constraint; no data migration, 0
  rows use `work`) + two nullable columns. Additive otherwise.
- **Review workflow**: `Hut.save()`'s done-marking of sources and
  `HutSource.add()`'s done-demotion only trigger on `done`; verified
  safe for `rework` transitions.
- **Frontend**: review-status badges (`getReviewText`/`getReviewColor`)
  must learn `rework`; unknown-value fallback keeps it cosmetic until
  then. The API exposes `review_status` as a plain string — no schema
  change.
- **Cost**: assessment ≈ description tokens in, ~40 tokens out — the
  whole corpus ≈ $0.05–0.10 with `glm-5.3-flash`.
