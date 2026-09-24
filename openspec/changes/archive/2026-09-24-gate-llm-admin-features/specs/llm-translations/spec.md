## MODIFIED Requirements

### Requirement: Admin translate action (follow-up)
The Hut and GeoPlace admin SHALL provide both a changelist bulk action
(for selected objects) and a per-object change-form button that fill
empty translated fields using `translate_instance()` semantics —
existing translations are never overwritten — with one API call per
object and per-object results, skips and errors reported as admin
messages. The action and button (including their admin URLs) SHALL be
visible only when the translation API is configured
(`TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY` and
`TRANSLATION_MODEL` all set); when unconfigured the admin SHALL show
no LLM UI for translation, and the commands SHALL remain runnable from
the CLI, failing fast with their existing configuration error.

#### Scenario: Translate from the change form
- **WHEN** an editor triggers the translate button on a hut or geoplace
- **THEN** empty translated fields are filled from the record's main
  language and the form reloads showing the results

#### Scenario: Bulk action with mixed outcomes
- **WHEN** the changelist action runs on objects where some already have
  complete translations and one API call fails
- **THEN** complete objects are reported as skipped, the failing object
  is reported as an error, and the remaining objects are still processed

#### Scenario: UI hidden when API is unconfigured
- **WHEN** the admin renders without `TRANSLATION_*` configuration
- **THEN** the translate changelist action is not listed and the
  change form shows no translate button, with no error messages, and
  Django's built-in bulk actions (e.g. `delete_selected`) remain listed

#### Scenario: Runner registration absent when API is unconfigured
- **WHEN** the admin runner registry is built without `TRANSLATION_*`
  configuration
- **THEN** `update_translations` is absent from the runner list and the
  admin shows no Run link for it, while the CLI command still exists and
  fails fast with its configuration error

#### Scenario: Unconfigured API in admin
- **WHEN** the API was configured when the admin loaded but the
  configuration is missing when the action or button endpoint actually
  runs
- **THEN** the admin shows an actionable error message naming the
  missing configuration instead of raising a server error

#### Scenario: Button endpoint safety
- **WHEN** the change-form button endpoint receives a GET request, or a
  POST from a user without change permission on the model
- **THEN** it responds with 405 / 403 respectively and performs no work
