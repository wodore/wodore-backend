## 1. Email → MAILERS (core)

- [ ] 1.1 Settings: assemble `MAILERS = {"default": {"BACKEND": …, "OPTIONS": {HOST, PORT, USERNAME, PASSWORD, USE_TLS, TIMEOUT}}}` from the existing env vars in `server/settings/components/common.py` (or the mail-specific component), per-environment `BACKEND`: console (dev) / `server.core.email_backends.EmailBackend` (staging) / SMTP (production)
- [ ] 1.2 Remove every deprecated `EMAIL_*` setting write (`EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_TIMEOUT`) and map remaining readers (e.g. feedback footer, docs) to the mailer config
- [ ] 1.3 `server/core/email_backends.py`: accept the mailer `alias` kwarg explicitly; wire its SMTP parent from `OPTIONS`; keep `_original_to` subject-tagging behavior
- [ ] 1.4 health_check mail probe: bump `django-health-check` to a MAILERS-compatible release if available; otherwise keep the legacy probe with a documented guardrail exception (design D3)
- [ ] 1.5 Tests: default mailer used by `EmailMessage.send()`; staging rewrite of to/cc/bcc with subject tagging; rewrite-disabled passthrough; `alias` kwarg tolerance; `manage.py check` clean re `mail.W001` for all three environment configs

## 2. Admin action signatures

- [ ] 2.1 `server/apps/translations/admin_helpers.py`: update `get_actions()` to the `action_location` signature
- [ ] 2.2 Check unfold for the `get_action_choices()` fix; bump `django-unfold` if released, otherwise note the residual warning for the next bump
- [ ] 2.3 Tests: admin smoke on the translations change list (actions render, bulk action executes)

## 3. OAuth toolkit RFC 9700

- [ ] 3.1 Audit active clients/tokens for password-credentials grant usage (admin query on `Application.grant_type`, token introspection) and record the result here
- [ ] 3.2 If unused: set `OAUTH2_PROVIDER["COMPLIANT_BCP_RFC9700_PASSWORD_GRANT"] = True`; if used: migrate the client(s) to authorization-code first, then flip
- [ ] 3.3 Tests: a password-grant request is rejected per RFC 9700 once the flag is on

## 4. authlib.jose → joserfc

- [ ] 4.1 `server/settings/components/oidc.py` (+ any importer): replace `authlib.jose` jwt encode/verify with `joserfc` equivalents, keep key handling on authlib
- [ ] 4.2 Tests: OIDC token verification round-trip (existing oidc specs) green; no `AuthlibDeprecationWarning` in the suite

## 5. Pillow getdata

- [ ] 5.1 `server/apps/images/assessment.py`: `Image.getdata()` → `get_flattened_data()` (capability-guarded so the Pillow pin can move independently)
- [ ] 5.2 Tests: assessment result unchanged on fixture images (existing image specs)

## 6. Guardrail + rollout

- [ ] 6.1 pytest `filterwarnings`: error on the Django 7.0 deprecation category, with the documented third-party exceptions from design D3/D5 inline
- [ ] 6.2 Full suite green locally and in CI with the guardrail active
- [ ] 6.3 Staging: feedback mail reaches rewritten admin addresses; `manage.py check --deploy` clean
- [ ] 6.4 Production rollout notes: confirm PostgreSQL ≥ 15 / PostGIS ≥ 3.2 (Django 6.1 requirement, ops-owned)
