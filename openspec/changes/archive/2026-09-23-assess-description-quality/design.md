## Context

Hut `review_status` (`new`/`review`/`done`/`work`/`reject`) drives the
editorial workflow: admin actions set `done`/`review`/`reject`,
`Hut.save()` marks a hut's sources done when the hut reaches `done`, and
`HutSource.add()` demotes `done`→`review` when new source data arrives.
Current data: 420 `review`, 229 `new`, 1012 `done` — **`work` and
`reject` are unused** (0 rows each). The frontend renders status badges
via `getReviewText`/`getReviewColor` mappings. The translation stack
from `add-main-language-translations` (client, service, command) is in
place.

## Goals / Non-Goals

**Goals:**

- Every non-empty hut description gets an anchored 1–10 quality score
  in the record's `main_language`.
- Low scores surface as review work through the *existing* workflow
  (status + comment), not a parallel structure.
- Zero extra API calls when a hut is being translated anyway.
- Editors can filter "bad texts" in the admin and close the loop with
  the existing `done` action.

**Non-Goals:**

- Scoring translations (score the source; translations inherit).
- Auto-rewriting descriptions (assessment only; rewriting is human).
- Scoring empty descriptions (structural gap, not quality).
- GeoPlace scoring (rare/short descriptions — add later if wanted).

## Decisions

### D1: reuse review workflow; rename unused `work` → `rework`

The LLM flags bad texts through `review_status` instead of a parallel
flag. `work` already carries the right semantics but is unused (0 rows)
and vague; renaming its value to `rework` (label "needs rework") is free
now — no data migration, the constraint regenerates — and the frontend
badge map must learn the value anyway because assessment will start
setting it. `HutSource`'s separate enum is left untouched.

### D2: conservative transition policy

| current status | score ≥ threshold | score < threshold |
|---|---|---|
| `done` | score only | `done → rework` |
| `new` / `review` | score only | score only (already queued) |
| `rework` / `reject` | score only | score only |

The LLM never *raises* status (that's the human's "mark done"), never
touches `reject`, and doesn't churn the already-queued states.
Threshold: `--review-below N`, default from
`TRANSLATION_QUALITY_REVIEW_THRESHOLD` (5).

### D3: rationale lives in `review_comment` as a marked block

No new note column. The assessment writes/updates a block
`[LLM 2026-09-23 · quality 4/10] <summary>` — replacing only the
LLM's *own* previous block (matched by the `[LLM ` marker), appending
otherwise. Human text is never removed. Length capped at the field's
10k.

### D4: minimal quality fields

`description_quality` (`PositiveSmallIntegerField`, null, check 1–10 or
NULL) + `description_quality_at` (datetime, null). `NULL` = never
assessed; empty description ⇒ stays `NULL`. No index (≈1.7k rows;
revisit if GeoPlace joins). Editors override nothing — the score is
advisory metadata, `review_status` stays the single source of workflow
truth.

### D5: anchored rubric, deterministic settings

One shared rubric constant in `llm.py` used by both prompt paths:
`1–2 unusable · 3–4 too thin/marketing-only · 5–6 adequate basics ·
7–8 good (facilities, season, access) · 9–10 excellent`. Assessment
runs at temperature 0. Response contract `{"score": int, "summary":
str}` (≤ 300 chars, single sentence + optional issue list).

### D6: piggyback on translation + standalone command

Two entry points, one storage path (`store_quality(hut, result)`):

1. **Piggyback**: `translate_instance()` already sends the source
   description — when the call happens and `description_quality` is
   NULL, the expected JSON gains `source_quality: {score, summary}`.
   Zero extra requests.
2. **Standalone `assess_descriptions`**: covers huts that need no
   translations (the majority — 1012 `done` huts are largely
   translated) and `--rescore` runs.

Piggyback is why a shared rubric matters: scores from both paths must
be comparable.

### D7: assessment prompt parity

Same Swiss-domain system prompt, language conventions and injection
hardening as translation; the assessment variant swaps the task section
for the rubric and output contract.

## Risks / Trade-offs

- [LLM score drift across runs] → anchored rubric, temperature 0,
  `--rescore` for periodic re-baselining; score is advisory only.
- [Editor disagrees with a score] → they act on `review_status`, not
  the score; a stale score is cosmetic. `--rescore` refreshes.
- [Renamed value reaches frontend] → badge map fallback renders
  unknown values; add `rework` mapping in the next frontend release.
- [Piggyback couples two concerns in one prompt] → bigger response
  contract; mitigated by one shared code path and per-contract parsing
  (missing `source_quality` is tolerated, never fatal to translations).
- [`Hut.save()`/`HutSource.add()` interplay] → both only special-case
  `done`; `rework` transitions trigger nothing (verified in code).

## Migration Plan

1. Additive migration: two nullable columns + `review_status` AlterField
   (constraint regenerates with `rework`; 0 rows to rewrite).
2. Frontend: add `rework` to badge color/text maps (anytime; fallback
   is cosmetic).
3. Run `app assess_descriptions --all --limit 10`, spot-check summaries
   against the rubric, tune `--review-below`, then run the corpus.
4. Editors work the `rework` filter; close items with "mark done".

## Open Questions

- Rescore policy on description edits: auto-rescore when
  `description_quality_at < modified`? (Row-level `modified` is too
  coarse; a description-level dirty flag could follow if needed.)
- Extend to GeoPlace descriptions if OSM import quality becomes an
  editorial topic.
