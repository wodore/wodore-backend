## Context

`server.apps.translations` provides `translate_instance()` (empty-only,
one batched call per record) and `assess_instance()`/`store_quality()`
(anchored 1–10 score, `[LLM …]` comment block, duck-typed
`done → rework` transition via the model's `ReviewStatusChoices` class
attribute). Hut has quality fields + admin column/filter; GeoPlace has
translation support but no quality fields, and its status enum still
contains the unused `work` value. The admin uses Unfold
(`server.apps.manager.admin.ModelAdmin`), with existing changelist
actions on Hut (done/review/reject) and `@display` label maps.

## Goals / Non-Goals

**Goals:**

- Editors can translate and assess from the admin without a terminal.
- GeoPlace reaches parity: quality fields, `rework` status, transitions.
- Bulk and single-object flows, safe and observable.

**Non-Goals:**

- Changing translation/assessment service semantics (reuse as-is).
- Public API changes; frontend badge updates (noted, separate repo).
- Auto-triggering assessment on save (explicit actions only).

## Decisions

### D1: changelist actions + change-form buttons, one shared mixin

A `LLMAdminMixin` in `server.apps.translations.admin_helpers` provides
the two `@admin.action`s (translate/assess) and wires a POST-only view
per ModelAdmin (`get_urls` addition, e.g. `llm-translate/<pk>`).
Hut and GeoPlace admins inherit the mixin. One implementation, two
model admins, no duplication. *Alternative:* copy-paste per admin —
drifts immediately.

### D2: buttons via object-tools on the change form

Minimal template override rendering two object-tools buttons (Translate,
Assess) that POST to the mixin's view (CSRF via the admin form context)
and redirect back to the change form. Staff permission
(`has_change_permission`) + POST-only (GET returns 405). *Alternative:*
full custom change_form_template with inline forms — heavier, no gain.

### D3: errors are messages, never exceptions

Client construction and per-object calls are wrapped: configuration
problems yield one actionable error message ("set TRANSLATION_API_*");
per-object `TranslationError`s become per-object error messages; the
action continues with the remaining objects. Skips (empty, unsupported,
already scored) are reported as info counts. Mirrors the command's
error-isolation contract.

### D4: GeoPlace parity reuses Hut patterns verbatim

`_ReviewStatusChoices` TextChoices with class attribute (Hut pattern),
quality fields + `description_quality_valid` constraint, migration with
`work`→`rework` constraint regeneration (0 rows → no data migration).
References to update: model choices, check constraint, admin label map
(`"work": "danger"` → `"rework"`), `ReviewStatus` schema enum in
`schemas/_input.py`. `store_quality()` needs no changes — the
`ReviewStatusChoices` attribute activates the transition. Verified: no
public visibility filter depends on geoplace `review_status` (API
serializes it; tiles filter on is_public/is_active only).

### D5: command moves to the translations app

`assess_descriptions` now covers two models; its natural home is
`server.apps.translations/management/commands/` beside
`update_translations` (same selector shape: `--hut/--geoplace/--model …
--all`). Command name unchanged; test patch-path updated. Command was
introduced in #158 and never deployed — the move is free.

## Risks / Trade-offs

- [Bulk action cost] → one call per object, results/skips visible in the
  message stream; no scheduler involvement.
- [Renamed `work` reaches place badges] → frontend fallback renders
  unknown values; `WdPlaceActions` should learn `rework` (noted in PR).
- [Button view CSRF/permissions] → POST-only + `has_change_permission`
  + admin CSRF token from the form; GET → 405.

## Migration Plan

1. Additive `geometries` migration (fields, constraint, status
   AlterField) — rollback drops columns and restores the constraint.
2. Deploy with #158's rollout (Infisical `TRANSLATION_*` vars).

## Open Questions

- None blocking; frontend badge mapping tracked outside this repo.
