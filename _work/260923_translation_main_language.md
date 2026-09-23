# Translation main language + LLM translations (PR 1)

Date: 2026-09-23 · Branch: `feature/translations-main-language`

## Context

Hut and GeoPlace texts are stored with django-modeltrans (`i18n` JSONB,
base columns = German). Until now there was no notion of a record's *main
language*: imports picked the first non-empty name in a hard-coded
de→en→fr→it order, and empty translations had to be filled manually
(see #155, where fr/it hut type texts were hand-translated).

## What changed

### Models

- `Hut.main_language` and `GeoPlace.main_language` — choices from
  `settings.LANGUAGES`, default `de`, CheckConstraint
  `*_main_language_valid`.
- `TranslationField(..., fallback_language_field="main_language")` —
  modeltrans 0.9 per-record fallback: a French-main-language hut now
  resolves `name_i18n` from `name_fr` even in a German request context.
- Auto-detect on import: `detect_main_language()` (in
  `server/apps/translations/detect.py`) picks the first non-empty name
  in `LANGUAGE_CODES` order. Wired into `Hut.create_from_schema`,
  `Hut.update_from_schema`, `GeoPlace._create_from_schema` and
  `GeoPlace._update_from_schema`.
- Admin: `main_language` added to the name-translation tabs of the Hut
  and GeoPlace fieldsets.
- Migrations: `huts/0060_hut_main_language.py`,
  `geometries/0042_geoplace_main_language.py` (applied to dev DB).

### LLM translation (`server/apps/translations/`)

- `llm.py` — `TranslationClient`: minimal OpenAI chat-completions
  client (httpx, JSON mode, retries on 408/429/5xx, code-fence-tolerant
  JSON parsing). Configured via env (Infisical):
  `TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY`,
  `TRANSLATION_MODEL`, `TRANSLATION_API_TIMEOUT`.
- `service.py` — `translate_instance()`: reads sources from
  `main_language`, fills only *empty* target fields in one API call per
  record, length-guards against field limits, saves with
  `update_fields` (GeoPlace with `track_modifications=False` so machine
  translations don't protect records from source updates).
- `update_translations` command: `--hut/--geoplace SLUG`, `--model
  hut|geoplace --all`, `--languages`, `--limit`, `--overwrite`,
  `--dry-run`. Dry-run needs no API config (planning mode).
- Removed dead `translate.py` (DeepL/argos stub, NotImplementedError).

### z.ai note

The GLM *Coding Plan* key/endpoint must NOT be used for this — its terms
restrict usage to supported coding tools (scripted/SDK usage may be
throttled). Use the pay-as-you-go general API
(`https://api.z.ai/api/paas/v4`) with any GLM model, OpenAI, or a local
server (Ollama `http://localhost:11434/v1`). All are drop-in via env.

### Incidental lint cleanup (`_geoplace.py`)

- `except (DatabaseError, Exception)` → `except Exception` (redundant
  tuple), retryable-DB-error check extracted to module constant
  `RETRYABLE_DB_MESSAGES` (boolean-free except body),
  `pyright: ignore` comments on plugin-less django-stubs artifacts
  (`category.id`, `amenity_detail`, `class Meta` override) — same
  convention the codebase already uses elsewhere.

## Tests

`tests/apps/translations/` — 30 tests: detect priority, client
(MockTransport: parsing, fences, filtering, retries, config errors),
service (empty-only fills, main-language sourcing, default-column
writes, overwrite, dry-run, length guard, geoplace no-modify-tracking,
fallback chain), command (selectors, language filter, limits, errors).

Full suite: 76 passed.

## Notable finding: `refresh_from_db` vs `from_db`

`Hut.save()` relies on `_orig_slug`/`_orig_review_status`, set only in
`Hut.from_db()`. `instance.refresh_from_db()` copies column values but
does NOT re-run `from_db`, so double-saving a factory-built instance
raises `AttributeError`. Test helper re-fetches via
`Hut.objects.get()` instead. Something to keep in mind for any code
path that creates-then-modifies-then-saves in memory.

## Next (PR 2)

- Admin "Translate" button on Hut/GeoPlace change form + changelist
  action calling `translate_instance()` (service is ready to reuse).
- Possibly extend to HutType / Owner / Categories translated fields.

## Pre-existing issues observed (not addressed)

- `django_admin_runner`/`django_q` model drift vs shipped migrations
  (`makemigrations --check` fails on main, unrelated third-party apps).
- `server.apps.images.api` standalone import raises ninja `ConfigError`
  (also on main; only surfaces when imported outside URLconf).
