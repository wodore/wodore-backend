# description-quality Specification

## Purpose
TBD - created by archiving change assess-description-quality. Update Purpose after archive.
## Requirements
### Requirement: Quality score storage on Hut
The system SHALL store an assessment of the main-language description
on `Hut` and `GeoPlace` as `description_quality` (integer 1–10, `NULL` =
never assessed, check-constrained to 1–10 or `NULL`) together with the
assessment time `description_quality_at`, and SHALL leave both fields
`NULL` when the description is empty.

#### Scenario: Empty description is never scored
- **WHEN** a hut or geoplace has no text in its `main_language`
  description field
- **THEN** no assessment call is made and `description_quality` remains
  `NULL`

#### Scenario: Database rejects out-of-range scores
- **WHEN** a value outside 1–10 is written to `description_quality`
- **THEN** the write is rejected by the check constraint

#### Scenario: Geoplace storage
- **WHEN** a geoplace with a description is assessed
- **THEN** the score and assessment time are stored on the geoplace row

### Requirement: Anchored-rubric assessment
Assessments SHALL score the `main_language` description against a fixed, anchored rubric (1–2 unusable, 3–4 too thin or marketing-only, 5–6 adequate basics, 7–8 good, 9–10 excellent) at deterministic settings, returning a score and a one-line summary, with the same rubric applied in every assessment path.

#### Scenario: Comparable scores across paths
- **WHEN** the same description is assessed standalone and during a translation run
- **THEN** both scores come from the same rubric prompt and are comparable

#### Scenario: Rationale is stored in the review comment
- **WHEN** an assessment completes
- **THEN** `review_comment` contains a marked block `[LLM <date> · quality <n>/10] <summary>` that replaces only a previous LLM block and never removes human-written text

### Requirement: Review workflow integration via rework status
The unused `work` review status SHALL be renamed to `rework` ("needs
rework"; no data migration — zero rows use `work`) on both `Hut` and
`GeoPlace`, and assessments SHALL move a record from `done` to `rework`
when the score is below the rework threshold (default 5), while records
in `new`, `review`, `rework` or (on Hut) `reject` SHALL keep their
status regardless of score.

#### Scenario: Bad description on a finished hut
- **WHEN** a `done` hut is assessed with score 4 and threshold 5
- **THEN** its `review_status` becomes `rework` and the LLM block is
  written to `review_comment`

#### Scenario: Bad description on a finished geoplace
- **WHEN** a `done` geoplace is assessed with score 4 and threshold 5
- **THEN** its `review_status` becomes `rework` and the LLM block is
  written to `review_comment`

#### Scenario: Already-queued records are not churned
- **WHEN** a hut or geoplace in `new` or `review` is assessed with
  score 3
- **THEN** its `review_status` is unchanged (only the score is stored)

#### Scenario: Human closes the loop
- **WHEN** an editor rewrites the description and uses the existing
  mark-done action
- **THEN** the record is `done` again and no automatic mechanism
  overrides it until a future assessment runs

### Requirement: Combined translation-time assessment
When a translation call is made for a hut whose `description_quality` is `NULL` and whose source description is non-empty, the system SHALL request the source quality in the same API call (`source_quality` field in the response) and store it through the same path as standalone assessment, at zero additional API requests.

#### Scenario: Free score during translation
- **WHEN** `update_translations` translates a hut with an unscored description
- **THEN** the single API call returns translations plus `source_quality`, and both are stored

#### Scenario: Missing quality field does not break translations
- **WHEN** a translation response omits `source_quality`
- **THEN** the translations are still stored and the omission is not an error

#### Scenario: Already scored hut translates without rescoring
- **WHEN** a hut with an existing `description_quality` is translated (without `--rescore`)
- **THEN** no quality is requested or overwritten

### Requirement: assess_descriptions command
The `assess_descriptions` management command SHALL support `--hut SLUG`
and `--geoplace SLUG` (repeatable), `--model hut|geoplace` with `--all`,
`--limit`, `--rescore` (re-assess already-scored records), and
`--rework-below N` (rework-threshold override), SHALL by default
assess only records with `NULL` scores and non-empty main-language
descriptions, and SHALL report per-record scores and a run summary.

#### Scenario: First corpus run
- **WHEN** `app assess_descriptions --all` runs
- **THEN** every hut with a non-empty description and no score is
  assessed exactly once, and records below the threshold appear in the
  output

#### Scenario: Geoplace selectors
- **WHEN** `app assess_descriptions --geoplace <slug>` runs
- **THEN** that geoplace's description is assessed and scored

#### Scenario: Rescore refreshes stale scores
- **WHEN** `app assess_descriptions --hut <slug> --rescore` runs
- **THEN** the existing score and comment block are replaced with fresh
  values

#### Scenario: API errors do not abort the run
- **WHEN** an assessment call fails after retries
- **THEN** the error is reported for that record and the run continues
  with the remaining records

### Requirement: Admin assess action
The Hut and GeoPlace admin SHALL provide a changelist bulk action and a
per-object change-form button that assess the main-language description
via `assess_instance()`, storing the score and comment block and
applying the `done → rework` transition; skips (empty description,
unsupported model, already scored) and per-object errors SHALL be
reported as admin messages. The action and button (including their
admin URLs) SHALL be visible only when the translation API is
configured (`TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY` and
`TRANSLATION_MODEL` all set); when unconfigured the admin SHALL show no
LLM UI for assessment, and the command SHALL remain runnable from the
CLI, failing fast with its existing configuration error.

#### Scenario: Assess from the change form
- **WHEN** an editor triggers the assess button on a described,
  unscored hut or geoplace
- **THEN** the score is stored, the `[LLM …]` block is written to the
  review comment, and the form reloads showing the result

#### Scenario: Skips are reported
- **WHEN** the assess action runs on objects with empty descriptions or
  existing scores
- **THEN** those objects are reported as skipped with the reason and no
  API call is made for them

#### Scenario: UI hidden when API is unconfigured
- **WHEN** the admin renders without `TRANSLATION_*` configuration
- **THEN** the assess changelist action is not listed and the change
  form shows no assess button, with no error messages, while Django's
  built-in bulk actions remain listed and `assess_descriptions` is
  absent from the admin runner registry (CLI command unchanged)
