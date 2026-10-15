# Design: Django 7.0 deprecation cleanup

## Context

Django 6.1 introduced the `MAILERS` setting and deprecated the whole
`EMAIL_*` family (`RemovedInDjango70Warning`). The installed 6.1.1 source
(`django/core/mail/handler.py`, `django/core/checks/mail.py`) defines the
target shape:

```python
MAILERS = {
    "default": {  # DEFAULT_MAILER_ALIAS — required once MAILERS exists (mail.W001)
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",  # optional, SMTP default
        "OPTIONS": {  # kwargs of the backend class, e.g. for SMTP:
            "HOST": ...,
            "PORT": ...,
            "USERNAME": ...,
            "PASSWORD": ...,
            "USE_TLS": ...,
            "USE_SSL": ...,
            "TIMEOUT": ...,
        },
    },
}
```

`django.core.mail.send_mail` / `EmailMessage.send()` keep working unchanged —
they route through the `default` mailer. Sending with a specific mailer uses
`using=<alias>`. A system check (`mail.W001`) warns when `MAILERS` exists
without a `"default"` entry; a deploy check (`deploy=True`) errors when the
default backend is a development-only backend.

## Goals

- Zero `RemovedInDjango70Warning` in the test suite.
- No behavior change: same recipients, same staging rewrite, same health
  checks, same admin behavior.

## Decisions

### D1 — Single `default` mailer, built from the existing env vars

Environments keep reading the same env vars they read today and assemble them
into `MAILERS["default"]` (`OPTIONS.HOST/PORT/USERNAME/PASSWORD/USE_TLS/
TIMEOUT` — SMTP backend kwarg names differ from the old `EMAIL_*` names, the
mapping is mechanical). Per-environment backend selection moves from
`EMAIL_BACKEND` to `MAILERS["default"]["BACKEND"]`:

- development: console backend (unchanged)
- staging: the address-rewrite backend (see D2)
- production: SMTP backend (unchanged)

No named multi-mailer topology for now; `using=` stays unused. If a second
mailer is ever needed, the alias system is already in place.

### D2 — Staging rewrite backend ports as a plain `BACKEND`

`server/core/email_backends.py` already implements the `BaseEmailBackend`
contract (`send_messages`). It moves to
`MAILERS["default"]["BACKEND"] = "server.core.email_backends.EmailBackend"`.
Two mechanical adaptations:

- Django instantiates mailer backends with `alias=<mailer alias>` — the class
  inherits `BaseEmailBackend` and already swallows unknown kwargs; add an
  explicit note/test so this never regresses.
- `OPTIONS` pass-through means the rewrite backend needs no special casing for
  its SMTP parent — it wraps whatever `OPTIONS` it is given.

### D3 — health_check mail probe

`health_check.contrib.mail` reads `EMAIL_BACKEND` and emits deprecation
warnings itself. Prefer a health_check release with MAILERS support (pin
bump); if none exists when this change lands, keep the probe on the legacy
settings until upstream catches up and track it — the suite-wide warning gate
(D6) gets a narrow `ignores` entry for that third-party path, documented here.

### D4 — OAuth password-grant: audit, then flip

django-oauth-toolkit flips `COMPLIANT_BCP_RFC9700_PASSWORD_GRANT` to `True`
in 4.0, rejecting non-compliant password-grant requests. We adopt the flag
explicitly, on our schedule: first audit active tokens/clients for
password-grant usage (token introspection + `Application` grant-type query in
admin). Expected result: no usage (auth is OIDC via Zitadel); then set the
flag to `True` in settings. If the audit finds real clients, migrate them to
the authorization-code flow first and only then flip — the flip must never
ship while a client still depends on it.

### D5 — Mechanical swaps, no behavior change

- `translations/admin_helpers.py`: add `action_location` to the
  `get_actions()` override (matching the new Django signature); unfold bump
  only if its fix is released — otherwise the unfold-side warning stays
  covered by the guardrail ignore for that file and is re-checked on the next
  unfold bump.
- `oidc.py`: replace `authlib.jose` imports with `joserfc` (jwt encode/verify
  only; key handling stays on authlib).
- `images/assessment.py`: `Image.getdata()` → `get_flattened_data()` behind a
  small capability check so the Pillow pin can move independently.

### D6 — Guardrail: fail the suite on email deprecations

Once the inventory is clear, add a pytest `filterwarnings` entry turning the
deprecation category into an error, with the (short) list of accepted
third-party exceptions from D3/D5 documented inline. This is the mechanism
that prevents a repeat of the silent-`**extra` class of surprise at Django 7.

## Out of scope

- Production PostgreSQL/PostGIS version verification (ops task tracked in the
  proposal's impact section).
- Introducing named multi-mailer topologies, retry/queue semantics for email.
- Any change to email content, recipients, or feedback endpoint behavior.

## Migration / rollout

1. Settings + backends + tests land together (no deploy-time toggle needed —
   the env contract is unchanged, only its consumer).
2. Staging verifies: feedback mail reaches rewritten admins; production-path
   mail (SMTP OPTIONS) verified via `manage.py sendtestemail` equivalent.
3. `manage.py check --deploy` clean (no `mail.W001` / development-backend
   error) on staging and production configs.
