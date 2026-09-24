# llm-translations Specification

## Purpose
TBD - created by archiving change add-main-language-translations. Update Purpose after archive.
## Requirements
### Requirement: Provider-agnostic translation client configuration
The system SHALL provide an LLM translation client speaking the
OpenAI chat-completions protocol (JSON mode), configured exclusively
via the `TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY`,
`TRANSLATION_MODEL` and `TRANSLATION_API_TIMEOUT` settings, and SHALL
raise `ImproperlyConfigured` when a translation is requested while the
base URL, key or model is unset. The GLM Coding Plan endpoint SHALL
NOT be used (its terms restrict usage to coding tools).

#### Scenario: Missing configuration
- **WHEN** `update_translations` runs without `--dry-run` and any
  `TRANSLATION_*` variable is unset
- **THEN** the command fails with a `CommandError` naming the missing
  configuration

#### Scenario: Retriable API failures
- **WHEN** the API answers 408/409/429 or 5xx
- **THEN** the client retries up to three times with backoff before
  raising `TranslationError`

#### Scenario: Malformed API responses
- **WHEN** the response body is not valid JSON, is not an object, or is
  wrapped in code fences
- **THEN** code fences are stripped; otherwise a `TranslationError` is
  raised and unrequested languages or empty field values are dropped

### Requirement: Empty-only translation semantics
`translate_instance()` SHALL read source texts from the record's
`main_language` (falling back to the default language), SHALL translate
only fields that are empty in their target language (unless
`overwrite` is set), SHALL batch all missing fields and languages of a
record into a single API call, and SHALL skip fields without source
text.

#### Scenario: Existing translation is never touched
- **WHEN** a hut has a human-made `i18n.name_fr` and an empty
  `description_fr`, and is translated with target `fr`
- **THEN** only `description_fr` is written; `name_fr` is unchanged

#### Scenario: Translating into the default language
- **WHEN** a hut with `main_language = "fr"` is translated with target
  `de`
- **THEN** the German result is stored in the base column (`name`,
  `description`), not in `i18n`

#### Scenario: Over-long results
- **WHEN** a translation exceeds the target field's `max_length`
- **THEN** the field is skipped with a warning and the value is not
  truncated

#### Scenario: No work available
- **WHEN** every requested target field is already filled or no source
  text exists
- **THEN** no API call is made and the record is not saved

### Requirement: Machine translations do not mark records modified
Saved LLM translations SHALL NOT mark geoplace records as manually
modified (no `is_modified`/protected-fields side effects) and SHALL
use partial updates limited to the touched columns.

#### Scenario: Geoplace stays unprotected
- **WHEN** a geoplace is translated via the service
- **THEN** `is_modified` remains false and subsequent source imports
  may still update the record's fields

### Requirement: update_translations command
The `update_translations` management command SHALL support selecting
records by `--hut SLUG` / `--geoplace SLUG` (repeatable) or
`--model hut|geoplace` with `--all`, restricting targets via
`--languages`, capping bulk runs via `--limit`, and replacing existing
translations only with `--overwrite`. It SHALL report per-record
results and a run summary, and SHALL continue after per-record
translation errors.

#### Scenario: Dry-run without API access
- **WHEN** the command runs with `--dry-run` and no `TRANSLATION_*`
  configuration
- **THEN** it reports the planned translations per record without
  calling the API and without saving

#### Scenario: Language filter
- **WHEN** `--languages fr` is passed
- **THEN** only French is requested from the API, independent of the
  other configured languages

#### Scenario: Unknown selector values
- **WHEN** an unknown slug or language code is passed, or no selector
  at all
- **THEN** the command fails with a `CommandError` naming the problem

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
