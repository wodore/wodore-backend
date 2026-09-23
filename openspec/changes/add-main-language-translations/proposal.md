## Why

Hut and geoplace texts are stored with django-modeltrans (`i18n` JSONB,
base columns = German), but records have no notion of their *main
language*: imports silently pick the first non-empty name in a
hard-coded de→en→fr→it order (a French-only source ends up with French
text in the German base columns), and empty translations in the other
configured languages must be filled by hand (see the manual fr/it work
in PR #155). We need an explicit per-record source language and a way
to fill missing translations automatically, with an LLM, without
touching human-made translations.

## What Changes

- **`main_language` on Hut and GeoPlace**: choices from
  `settings.LANGUAGES` (default `de`), check-constrained, editable in
  the admin name-translation tabs, and auto-detected on schema imports
  (first non-empty name in `LANGUAGE_CODES` order).
- **Per-record fallback chains**: both models pass
  `fallback_language_field="main_language"` to their `TranslationField`
  so `name_i18n`-style lookups fall back to the record's main language
  before the configured chain — a French-main-language hut with empty
  German columns now resolves its French name instead of returning
  empty.
- **LLM translation backend** (`server.apps.translations`, now a
  registered app): an OpenAI-chat-completions-compatible client
  (`TranslationClient`) configured via env vars (Infisical) — works with
  the z.ai *general* GLM API, OpenAI, or a local server (Ollama); the
  z.ai *GLM Coding Plan* endpoint is explicitly out (its terms restrict
  usage to coding tools).
- **`translate_instance()` service**: fills only *empty* translated
  fields from the record's main language in a single API call per
  record; length-guards field limits; saves with `update_fields` and
  `track_modifications=False` on geoplaces so machine translations
  never protect records from source updates.
- **`update_translations` management command**: `--hut/--geoplace SLUG`,
  `--model hut|geoplace --all`, `--languages`, `--limit`,
  `--overwrite`, `--dry-run` (dry-run plans without API config).
- **Admin translate button** (follow-up PR): per-object button and
  changelist action on Hut/GeoPlace calling the same service.
- Removes the dead `translate.py` DeepL/argos-translate stub.

## Capabilities

### New Capabilities

- `main-language`: per-record main language on translated models —
  field semantics, import auto-detection, database constraints, and
  per-record fallback resolution.
- `llm-translations`: LLM-backed filling of empty translated fields —
  provider-agnostic client configuration, translation semantics
  (empty-only by default, single batched call, length guards, save
  behaviour), and the `update_translations` command CLI.

### Modified Capabilities

(none — no existing spec's requirements change)

## Impact

- **Models/migrations**: `huts/0060_hut_main_language.py`,
  `geometries/0042_geoplace_main_language.py` (additive only; existing
  rows default to `de`). Applied to dev; must ship with a deploy.
- **APIs**: no endpoint changes; `name_i18n` resolution *improves* for
  non-German-main records (previously empty).
- **Dependencies**: none new (httpx already a dependency).
- **Config**: four new env vars — `TRANSLATION_API_BASE_URL`,
  `TRANSLATION_API_KEY`, `TRANSLATION_MODEL`,
  `TRANSLATION_API_TIMEOUT` — to be added to Infisical before the
  first bulk run; without them only `--dry-run` works.
- **Cost/ops**: bulk `--all` runs call a paid API once per record with
  missing translations; `--limit` and dry-run planning are the guard
  rails.
