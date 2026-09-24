## MODIFIED Requirements

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
