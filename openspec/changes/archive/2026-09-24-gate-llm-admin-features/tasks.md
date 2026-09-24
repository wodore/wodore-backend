## 1. OpenSpec

- [x] 1.1 `gate-llm-admin-features` change: proposal, design (incl. import-time registration trade-off), MODIFIED deltas for `llm-translations` + `description-quality`, this task list; `openspec validate` green

## 2. Single source of truth

- [x] 2.1 `translations_api_enabled()` in `server/apps/translations/llm.py` (all three `TRANSLATION_*` vars set; no new env var)

## 3. Admin gating (`LLMAdminMixin`)

- [x] 3.1 `get_actions()` filters the actions out when disabled
- [x] 3.2 `get_urls()` omits the LLM button views when disabled (prevents `NoReverseMatch`)
- [x] 3.3 `render_change_form()` sets `llm_*_url` context only when enabled (template `{% if %}` guards hide the buttons)
- [x] 3.4 `_build_client` defensive config-error handling retained

## 4. Admin-runner registration gating

- [x] 4.1 `update_translations` + `assess_descriptions`: import-time conditional `@register_command` (identity decorator when unconfigured); CLI behavior unchanged

## 5. Tests

- [x] 5.1 Enabled matrix: actions listed, buttons rendered, URLs resolve, runner entries registered (module reload under `override_settings`, registry cleanup)
- [x] 5.2 Disabled matrix (default env): actions absent, no button context, LLM URLs absent, runner entries absent
- [x] 5.3 CLI: `CommandError` still raised when unconfigured; existing suite stays green

## 6. Gates

- [x] 6.1 ruff check --fix + ruff format on touched files
- [x] 6.2 Full pytest suite green (isolated `POSTGRES_DB=wodore_lane_flag`)
- [x] 6.3 `openspec validate gate-llm-admin-features` green
