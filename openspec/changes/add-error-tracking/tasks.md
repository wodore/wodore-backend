## 1. Dependency & Settings Component

- [x] 1.1 Add `sentry-sdk>=2.72,<3` to `pyproject.toml` dependencies and run `uv sync --extra private` (update `uv.lock`)
- [x] 1.2 Create `server/settings/components/sentry.py`: DSN-gated `sentry_sdk.init` (no init when `SENTRY_DSN` unset) with `release=GIT_HASH` (uniform across envs), `environment=ENVIRONMENT`, semver from `importlib.metadata.version("wodore-backend")` attached as `app_version` tag (via `before_send`), `send_default_pii=False`, explicit `LoggingIntegration(level=INFO, event_level=ERROR)`, `AsyncioIntegration()`, health-check exclusion + `SENTRY_TRACES_SAMPLE_RATE` (default 0.05) via a minimal `traces_sampler` (sentry-sdk 2.72 has no `ignore_transactions` option)
- [x] 1.3 Include `components/sentry.py` FIRST in `_base_settings` in `server/settings/__init__.py` (before `components/logging.py`)

## 2. Configuration & Docs

- [ ] 2.1 Add `SENTRY_DSN` (and optional `SENTRY_TRACES_SAMPLE_RATE`) to Infisical staging/production; verify `.env.test` and dev defaults stay DSN-free *(blocked on vendor decision 5.1)*
- [x] 2.2 Document the error-tracking setup in `AGENTS.md`: env vars, PII-off rule, vendor-neutrality (DSN swap sentry.io ↔ Better Stack), rollback = unset DSN

## 3. Tests

- [x] 3.1 Test: settings import without `SENTRY_DSN` does not initialize the SDK (assert no client/DSN after import under `DJANGO_ENV=test`)
- [x] 3.2 Test: with a fake DSN monkeypatched, init is called with the expected `release` (GIT_HASH), `app_version` tag (package semver), `environment`, `send_default_pii=False`, sample rate, and `/health/` exclusion (via traces sampler, real sampling-context shapes)
- [x] 3.3 Run the lane test suite (`scripts/lane-run.sh .venv/bin/pytest`) — full suite green

## 4. Staging Validation (spec scenarios)

- [ ] 4.1 Deploy staging with DSN; trigger `sentry_sdk.capture_message` and a real 500 via a test request — verify event arrives with correct release/environment tag
- [ ] 4.2 Verify breadcrumbs from structlog events appear on a captured error and stdout JSON format is unchanged
- [ ] 4.3 Fail a django-q2 task on purpose; verify the error is captured from the qcluster process (via the in-repo `SentryErrorReporter`)
- [ ] 4.4 Verify `/health/` requests generate no transactions and sampled requests produce view/DB/httpx spans at the configured rate (both WSGI and ASGI runtimes)

## 5. Vendor Decision & Production Rollout

- [ ] 5.1 Evaluate Better Stack vs sentry.io during staging trial (error fidelity, spans ingestion on Better Stack, alerting); pick vendor and record the decision in `_work/` notes
- [ ] 5.2 Configure alert routing (Slack/email) at the chosen vendor; add inbound filters for noisy 4xx/bot traffic
- [ ] 5.3 Add `SENTRY_DSN` to Infisical production and roll out; monitor quota/spans volume and tune `SENTRY_TRACES_SAMPLE_RATE` if needed

## 6. Review Fixes (Claude Opus review — REQUEST_CHANGES, addressed)

- [x] 6.1 Sampler reads the real request path from the sampling context (`wsgi_environ.PATH_INFO` / `asgi_scope.path`) — transaction names are unresolved at sampling time (WSGI: "generic WSGI request") or full URLs (ASGI), so name-based matching never fired; `re` hoisted + pattern compiled once
- [x] 6.2 django-q2 task-failure capture: in-repo `SentryErrorReporter` (`server/core/q2_sentry.py`) via the `djangoq.errorreporters` entry point + `Q_CLUSTER["error_reporter"]`; captures the live `sys.exc_info()` inside the worker's except block (external `django-q-sentry` rejected: stale 2022 release, DB-string reconstruction)
- [x] 6.3 `app_version` tag also on transaction events (`before_send_transaction`)
- [x] 6.4 Tests rewritten to the real sampling-context shapes (fail on the old name-based implementation); q2 reporter wiring + inert/live behavior tests added
- [x] 6.5 AGENTS.md: residual-PII caveat (`send_default_pii=False` does not scrub PII embedded in log messages → breadcrumbs/events)
