## MODIFIED Requirements

### Requirement: Admin translate action (follow-up)
The Hut and GeoPlace admin SHALL provide both a changelist bulk action
(for selected objects) and a per-object change-form button that fill
empty translated fields using `translate_instance()` semantics —
existing translations are never overwritten — with one API call per
object and per-object results, skips and errors reported as admin
messages.

#### Scenario: Translate from the change form
- **WHEN** an editor triggers the translate button on a hut or geoplace
- **THEN** empty translated fields are filled from the record's main
  language and the form reloads showing the results

#### Scenario: Bulk action with mixed outcomes
- **WHEN** the changelist action runs on objects where some already have
  complete translations and one API call fails
- **THEN** complete objects are reported as skipped, the failing object
  is reported as an error, and the remaining objects are still processed

#### Scenario: Unconfigured API in admin
- **WHEN** the translate action is triggered without `TRANSLATION_*`
  configuration
- **THEN** the admin shows an actionable error message naming the
  missing configuration instead of raising a server error

#### Scenario: Button endpoint safety
- **WHEN** the change-form button endpoint receives a GET request, or a
  POST from a user without change permission on the model
- **THEN** it responds with 405 / 403 respectively and performs no work
