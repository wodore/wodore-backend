## 1. Main language model foundation (done in PR #156)

- [x] 1.1 Add `main_language` (`CharField(max_length=10, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE)`) and `fallback_language_field="main_language"` on the `TranslationField` to `Hut` and `GeoPlace`
- [x] 1.2 Add check constraints `huts_hut_main_language_valid` / `geometries_geoplace_main_language_valid`; migrations `huts/0060_hut_main_language.py`, `geometries/0042_geoplace_main_language.py` (additive only)
- [x] 1.3 Add `detect_main_language()` to `server.apps.translations` (first non-empty name in `LANGUAGE_CODES` order) and wire it into `Hut.create_from_schema`, `Hut.update_from_schema`, `GeoPlace._create_from_schema`, `GeoPlace._update_from_schema` (updates only when a name is present)
- [x] 1.4 Expose `main_language` in the Hut and GeoPlace admin name-translation tabs

## 2. LLM translation backend (done in PR #156)

- [x] 2.1 `server/apps/translations/llm.py`: `TranslationClient` — OpenAI chat-completions protocol, JSON mode, retries on 408/409/429/5xx with backoff, code-fence-tolerant parsing, `TranslationError`; explicit note that the GLM Coding Plan endpoint must not be used
- [x] 2.2 Settings: `TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY`, `TRANSLATION_MODEL`, `TRANSLATION_API_TIMEOUT` via `config()` in `components/common.py`
- [x] 2.3 `server/apps/translations/service.py`: `translate_instance()` — sources from `main_language`, empty-only fills (opt-in `overwrite`), single batched API call, field `max_length` guards, descriptor-based writes (default language → base columns), `update_fields` saves, `track_modifications=False` for geoplaces; `_Translator` protocol for testability
- [x] 2.4 Register `server.apps.translations` in `INSTALLED_APPS`; remove dead `translate.py` stub

## 3. Management command (done in PR #156)

- [x] 3.1 `update_translations` command: `--hut`/`--geoplace` (repeatable), `--model hut|geoplace` + `--all`, `--languages`, `--limit`, `--overwrite`, `--dry-run`
- [x] 3.2 Per-record error isolation with summary; `CommandError` on unknown slugs/languages/selectors and on unconfigured API (dry-run tolerates missing config)

## 4. Tests (done in PR #156)

- [x] 4.1 `test_detect.py` — priority order, empty values, custom priority
- [x] 4.2 `test_llm.py` — request shape/auth, parsing, fence stripping, filtering, retries, config errors (httpx MockTransport)
- [x] 4.3 `test_service.py` — empty-only semantics, main-language sourcing into base columns, overwrite, dry-run (no API/no save), length guard, geoplace no-modify-tracking, fallback-chain integration
- [x] 4.4 `test_command.py` — selectors, language filter, limit, error paths, dry-run without config

## 5. Admin translate action (follow-up PR — pending)

- [ ] 5.1 Add a change-form translate button (Hut, GeoPlace) calling `translate_instance()` server-side, respecting the current admin language context; reload the form with a success/error message
- [ ] 5.2 Add a changelist admin action for bulk translation of selected records (missing-fields-only; never overwrite)
- [ ] 5.3 Guard: actionable error message when `TRANSLATION_*` is unconfigured; tests for both entry points

## 6. Rollout

- [ ] 6.1 Add the four `TRANSLATION_*` variables to Infisical (dev first; e.g. z.ai general API `https://api.z.ai/api/paas/v4` + GLM model)
- [ ] 6.2 First bulk run: `app update_translations --model hut --all --limit 5`, spot-check, then widen; geoplaces afterwards
- [ ] 6.3 Archive this change once the admin action (§5) has shipped and been verified
