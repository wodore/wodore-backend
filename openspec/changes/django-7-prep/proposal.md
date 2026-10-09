# Django 7.0 deprecation cleanup

## Why

The Django 6.0.8 → 6.1.1 upgrade (#254) surfaced a new class of risk: renamed
kwargs that land in `**extra` are dropped **silently** (the aggregate
`ordering` → `order_by` rename cost us the availability day order, #298), and
the test suite now emits a steady stream of `RemovedInDjango70Warning`
deprecations that harden into breaks at the Django 7.0 upgrade. The audit
after #298 inventoried five items; this change clears all of them so the next
major upgrade is a version bump instead of a scramble.

## What Changes

- **Email → MAILERS** (the bulk of the work): replace every deprecated
  `EMAIL_*` setting (`EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`,
  `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`,
  `EMAIL_TIMEOUT`) with the Django 6.1+ `MAILERS` setting. The
  per-environment backend selection, the staging address-rewrite backend
  (`server/core/email_backends.py`), and the health-check mail probe must all
  keep working unchanged.
- **Admin action signatures**: `translations/admin_helpers.py` overrides
  `get_actions()` / the installed unfold overrides `get_action_choices()`
  without the new `action_location` parameter — update the signatures (and
  bump unfold if it ships the fix).
- **OAuth toolkit RFC 9700**: audit whether any active client uses the
  resource-owner password-credentials grant, then adopt
  `COMPLIANT_BCP_RFC9700_PASSWORD_GRANT = True` before django-oauth-toolkit
  4.0 flips the default for us, unannounced.
- **authlib.jose → joserfc**: `server/settings/components/oidc.py` uses the
  deprecated `authlib.jose` module; swap token verification to `joserfc`.
- **Pillow `Image.getdata`**: `server/apps/images/assessment.py` uses an API
  removed in Pillow 14; switch to `get_flattened_data`.
- **Guardrail**: after the cleanup, fail the test suite on
  `RemovedInDjango70Warning` so the next deprecation cycle cannot accumulate
  silently again.

## Impact

- **Affected**: `server/settings/components/*` (email/env wiring),
  `server/core/email_backends.py`, health-check configuration,
  `server/apps/translations/admin_helpers.py`, `server/apps/images/assessment.py`,
  `server/settings/components/oidc.py`, dependency pins (unfold,
  django-oauth-toolkit, authlib/joserfc, Pillow).
- **Not affected**: API contracts, availability endpoints, models/migrations.
  Email recipients, rewriting behavior, and delivery semantics stay exactly as
  they are (covered by the `email-delivery` spec delta).
- **Ops note**: production must run PostgreSQL ≥ 15 and PostGIS ≥ 3.2 for
  Django 6.1 itself (CI: `postgis:16-3.4`, local: 16.4) — verify when this
  change lands on production, not part of this change.
