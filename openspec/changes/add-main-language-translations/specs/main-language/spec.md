## ADDED Requirements

### Requirement: Main language field on translated models
`Hut` and `GeoPlace` SHALL have a `main_language` character field with
choices from `settings.LANGUAGES`, defaulting to
`settings.LANGUAGE_CODE`, constrained at the database level to the
configured language codes, and editable in the admin
name-translation tab.

#### Scenario: Default on existing rows
- **WHEN** the additive migrations are applied
- **THEN** every existing hut and geoplace has `main_language` set to
  `settings.LANGUAGE_CODE` (`de`)

#### Scenario: Database rejects unknown codes
- **WHEN** a record is saved with `main_language` not in
  `settings.LANGUAGE_CODES`
- **THEN** the write is rejected by the
  `*_main_language_valid` check constraint

### Requirement: Main language auto-detection on import
Imports SHALL set `main_language` to the first language (in
`settings.LANGUAGE_CODES` order) that provides a non-empty name when a
hut or geoplace is created or updated from a source schema, and SHALL
NOT overwrite an existing `main_language` when no name is present in
the incoming schema.

#### Scenario: French-only source
- **WHEN** a hut schema provides only `name_fr`
- **THEN** the hut is stored with `main_language = "fr"` and the French
  name in `i18n.name_fr`

#### Scenario: Multilingual source prefers configured order
- **WHEN** a geoplace schema provides `name_fr` and `name_it`
- **THEN** `main_language` is set to `fr` (de and en absent in
  `LANGUAGE_CODES` order)

#### Scenario: No names in update
- **WHEN** an update schema contains no name fields
- **THEN** the stored `main_language` remains unchanged

### Requirement: Per-record translation fallback
Translated-field lookups on `Hut` and `GeoPlace` (e.g. `name_i18n`)
SHALL try the record's `main_language` as the first fallback language
before the configured `MODELTRANS_FALLBACK` chain.

#### Scenario: French hut in German context
- **WHEN** a hut has `main_language = "fr"`, an empty base `name`
  column, and `i18n.name_fr` set
- **THEN** `hut.name_i18n` returns the French name instead of an empty
  value
