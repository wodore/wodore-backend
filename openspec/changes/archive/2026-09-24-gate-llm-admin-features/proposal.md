## Why

The translation stack (buttons, changelist actions, admin-runner
commands) is fully functional but assumes the LLM API is configured. On
checkouts/environments without `TRANSLATION_API_*` secrets the admin
still renders the LLM UI — clicking it produces configuration-error
messages ("noise"), and the Translations group appears in the admin
runner despite being unusable. The owner wants the surface visible only
when the API is actually usable (client-constructible: base URL, key
and model all set).

## What Changes

- **Single source of truth**: `translations_api_enabled()` in
  `server/apps/translations/llm.py` — true iff
  `TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY` and
  `TRANSLATION_MODEL` are all set. No new env var.
- **Admin mixin gating** (`LLMAdminMixin`): changelist actions omitted
  via `get_actions()` (Django-idiomatic filtering), button URLs not
  registered (`get_urls()`), and button context not set
  (`render_change_form`) when disabled — the template already hides on
  missing context vars. Buttons/actions/URLs disappear completely; no
  config-error messages are triggered by merely visiting the admin.
- **Admin-runner registration gating**: `update_translations` and
  `assess_descriptions` register with `@register_command` only when
  enabled at import time (import-time conditional decorator; tradeoff
  documented in design). CLI availability is untouched — commands still
  run from the shell and still fail fast with the clear
  `CommandError` when unconfigured.
- **Unchanged on purpose**: quality score column/filter stay visible
  (data display, not API), `_build_client`'s defensive
  `ImproperlyConfigured` handling stays as belt-and-suspenders.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `llm-translations`: "Admin translate action (follow-up)" gains
  conditional visibility on API configuration.
- `description-quality`: "Admin assess action" gains the same
  conditional visibility.

## Impact

- **Models/APIs**: none — admin presentation and runner registry only.
- **Settings**: reads the existing three `TRANSLATION_*` vars; no new
  configuration surface.
- **Trade-off**: admin-runner registration is import-time; changing the
  env requires a process restart for the admin list to follow (CLI
  commands always reflect the live env). Documented in design.md.
- **Tests**: enabled/disabled matrix via `override_settings` (runner
  registration test reloads the command modules under override and
  cleans the registry afterwards).
