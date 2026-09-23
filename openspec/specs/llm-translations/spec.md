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
The Hut and GeoPlace admin SHALL provide a per-record translate action
that fills empty translated fields using the same service semantics,
without overwriting existing translations.

#### Scenario: Translate from the change form
- **WHEN** an editor triggers the translate action on a hut
- **THEN** empty translated fields are filled from the record's main
  language and the form reloads showing the results

#### Scenario: Unconfigured API in admin
- **WHEN** the translate action is triggered without `TRANSLATION_*`
  configuration
- **THEN** the admin shows an actionable error message instead of
  saving partial state
