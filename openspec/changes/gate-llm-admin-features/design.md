## Context

The LLM admin surface (`LLMAdminMixin`: two changelist actions + two
change-form button views; `@register_command` on
`update_translations`/`assess_descriptions`) was built assuming the API
is configured. Settings carry three vars — `TRANSLATION_API_BASE_URL`,
`TRANSLATION_API_KEY`, `TRANSLATION_MODEL` — all empty by default;
`TranslationClient.__init__` raises `ImproperlyConfigured` when any is
missing. django-admin-runner registers commands via an import-time
decorator into a module-level `_registry` dict with **no unregister
API** (verified in `django_admin_runner/registry.py`); the admin list
and `CommandRunnerModelAdminMixin` Run links iterate that dict.

## Goals / Non-Goals

**Goals:**

- Zero LLM UI when the API is unconfigured: no actions, no buttons, no
  button URLs, no runner entries — silently, without error messages.
- One authoritative check, reused by admin and registration.
- CLI behavior unchanged (commands remain available and fail fast with
  the existing clear `CommandError`).

**Non-Goals:**

- Runtime re-evaluation of runner registration per request (needs an
  unregister hook the package does not offer).
- Hiding the quality score column/filter (data display, not API).
- A new `TRANSLATIONS_ENABLED` boolean (owner decision: gate on
  client-constructibility of the existing config).

## Decisions

### D1: `translations_api_enabled()` in `llm.py`

`bool(settings.TRANSLATION_API_BASE_URL and
settings.TRANSLATION_API_KEY and settings.TRANSLATION_MODEL)` — lives
next to `TranslationClient` (same config domain), evaluated at call
time so admin views react to `override_settings` in tests.

### D2: gate the mixin via Django's documented hooks

- `get_actions(request)`: return `()` when disabled (class-level
  `actions` tuple stays as the source list; filtering here is the
  Django-idiomatic conditional).
- `get_urls()`: omit the two LLM paths when disabled (prevents
  `NoReverseMatch` from a stale template context and hides the views).
- `render_change_form()`: set the `llm_*_url` context vars only when
  enabled; the template's existing `{% if %}` guards do the rest.
- `_build_client` keeps its `ImproperlyConfigured` catch —
  belt-and-suspenders against env changes between render and click.

### D3: import-time conditional runner registration

```python
_register = (
    register_command(group="Translations", models=[Hut, GeoPlace])
    if translations_api_enabled()
    else (lambda cls: cls)  # noqa: no-op registration when unconfigured
)


@_register
class Command(BaseCommand): ...
```

**Why:** `_registry` has no unregister; the admin reads it at render
time, so a request-time check would need mutation of package state.
Import time is also when Django loads management commands, and settings
are already configured then — the check is meaningful and stable.

**Trade-off (accepted):** the admin runner list reflects the env at
process start; flipping `TRANSLATION_*` requires a restart for the
admin list to follow. CLI commands always see the live env (their
fail-fast `CommandError` covers the unconfigured case).

**Tests:** the default test env has the vars unset → modules import
unregistered (assert absence directly). The "registered" case reloads
the command module under `override_settings` and removes the registry
entry afterwards — no package mutation leaks between tests.

## Risks / Trade-offs

- [Restart staleness of the runner list] → documented in AGENTS-facing
  proposal; CLI unaffected; `_build_client` guard retained for the
  click-after-env-change window.
- [Module reload in tests could leak registry entries] → test fixture
  pops the entry in a finally block.

## Migration Plan

None — no schema changes; deploy is code-only.

## Open Questions

(none)
