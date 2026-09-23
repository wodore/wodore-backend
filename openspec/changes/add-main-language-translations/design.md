## Context

django-modeltrans 0.9 stores translations per model: the default
language (`settings.LANGUAGE_CODE = "de"`) lives in the base columns
(`name`, `description`, `note`), other languages in the `i18n` JSONB,
with fallback chains from `MODELTRANS_FALLBACK`. Imports
(`hut_services` schemas for huts, OSM tags for geoplaces) deliver
mixed-language payloads; the code had no notion of a record's source
language and hard-coded a de→en→fr→it pick order. A dead
`translate.py` stub showed earlier DeepL/argos-translate experiments
that never shipped. Zero LLM client code existed; `httpx` is already a
dependency.

## Goals / Non-Goals

**Goals:**

- Explicit, per-record source language (`main_language`) on Hut and
  GeoPlace, maintained automatically on import and editable by editors.
- Correct i18n resolution for records whose texts are not German.
- Idempotent, cost-aware filling of *empty* translations via an
  OpenAI-compatible LLM API, usable both as a management command and
  (follow-up) from the admin.
- Provider freedom: z.ai general GLM API, OpenAI, or local Ollama via
  env vars only.

**Non-Goals:**

- Replacing human translations (empty-only default; `--overwrite` is
  opt-in and never the admin default).
- Translating *every* modeltrans model (HutType, Owner, Categories,
  … — candidates for a follow-up once the pattern proves out).
- Translation memory / glossary management, quality scoring, or
  automatic re-translation on source change.
- Frontend changes (the existing `lang` API params keep working).

## Decisions

### D1: `main_language` as a plain model field + modeltrans
`fallback_language_field`

modeltrans 0.9 natively supports per-record fallback
(`TranslationField(fallback_language_field=...)`): the record's
language is prepended to every fallback chain. Reusing that instead of
custom lookup logic means `name_i18n`/`description_i18n` resolve
correctly everywhere (API, admin, tiles) with zero new query code.
*Alternative considered:* storing the language inside `i18n` metadata
— invisible to the ORM, unqueryable, no admin integration.

Field: `CharField(max_length=10, choices=settings.LANGUAGES,
default=settings.LANGUAGE_CODE)` + CheckConstraint
(`main_language__in=settings.LANGUAGE_CODES`), matching the existing
constraint convention (`review_status_valid` et al.). `max_length=10`
follows Django convention (room for regional codes like `de-ch`).

### D2: auto-detection order = `settings.LANGUAGE_CODES` order

`detect_main_language()` picks the first non-empty name in configured
order (de, en, fr, it) — identical to the historic `primary_name()`
behaviour, so imports don't change semantics for existing data;
detection just makes the assumption explicit and editable. On updates
the detected value only overrides when a name is actually present.

### D3: provider-agnostic OpenAI-compatible client, not a vendor SDK

`TranslationClient` (httpx) speaks the chat-completions protocol with
`response_format={"type": "json_object"}` — supported by z.ai GLM,
OpenAI and Ollama alike. Config via four env vars (Infisical):
`TRANSLATION_API_BASE_URL`, `TRANSLATION_API_KEY`,
`TRANSLATION_MODEL`, `TRANSLATION_API_TIMEOUT`. Fail-fast
`ImproperlyConfigured` on missing config (mirrors the OIDC pattern).
*Alternatives considered:* the official OpenAI or z.ai SDKs (new
dependencies, vendor lock, no benefit for one endpoint);
DeepL (deterministic and cheap but weak for short contextual fields
like hut names and notes, and a second integration to maintain).

**Explicitly rejected:** the z.ai *GLM Coding Plan* endpoint/key. Its
terms restrict usage to supported coding tools; scripted/SDK usage may
be throttled. Only the pay-as-you-go general API
(`https://api.z.ai/api/paas/v4`) is permitted.

### D4: one API call per record; empty-only semantics

`translate_instance()` batches all missing (field, language) pairs of
a record into a single JSON-mode request with a domain prompt
(customary alpine place names, preserve markup/numbers). Only fields
with at least one missing target are sent. Non-empty translations are
never overwritten unless `overwrite=True` — human edits stay safe and
the command is idempotent. Results are length-checked against the
concrete field's `max_length` (over-long results are skipped with a
warning, not truncated — truncated hut names are worse than missing
ones).

Writes go through modeltrans descriptors
(`setattr(obj, f"{field}_{lang}", value)`), which route default-language
values into base columns and others into `i18n` — the same path admin
forms use. Saves use `update_fields` and, for GeoPlace,
`track_modifications=False` so LLM output never marks records
manually-modified (which would protect them from source updates).

### D5: dry-run requires no API config

`--dry-run` computes the plan from `missing` pairs without
constructing a client — planning is free and works on any checkout.
The command therefore constructs the client lazily and tolerates
missing config only in dry-run mode.

### D6: `update_translations` command shape

Selectors: `--hut SLUG` / `--geoplace SLUG` (repeatable) or
`--model hut|geoplace --all`; modifiers `--languages` (subset),
`--limit N` (bulk cost control), `--overwrite`, `--dry-run`. Per-record
errors are reported and don't abort the run; a summary counts processed
instances, translated fields and errors.

## Risks / Trade-offs

- [LLM output quality for proper nouns] → domain prompt demands
  customary local names; empty-only semantics keeps bad output out of
  existing good translations; `--limit` + dry-run for gradual rollout.
- [Bulk cost on `--all` (geoplaces ≫ huts)] → `--limit`, per-run
  summary, dry-run planning; no scheduling/cron in this change.
- [API unavailability mid-run] → retry with backoff on 408/429/5xx;
  per-record error isolation; idempotent re-runs.
- [Over-long translations] → skipped with warning (see D4), never
  truncated.
- [Wrong `main_language` yields cascading bad translations] →
  editable in admin; detection matches previous import behaviour; the
  fallback chain change only *adds* resolution where values were empty
  before.

## Migration Plan

1. Ship additive migrations (`huts/0060`, `geometries/0042`) — all
   existing rows default to `de`; rollback is
   `migrate huts 0059` / `migrate geometries 0041` (column drop).
2. Add the four `TRANSLATION_*` env vars to Infisical (any
   OpenAI-compatible endpoint).
3. First run: `app update_translations --model hut --all --limit 5`,
   spot-check, then raise/remove the limit. Geoplaces afterwards.
4. Follow-up PR adds the admin translate button on the same service.

## Open Questions

- Extend to HutType/Owner/Category translated fields — reuse is a
  one-line model addition plus admin wiring; wait for demand.
- Should bulk runs eventually be scheduled (django-q) with a
  translation-freshness policy? Out of scope until asked for.
