## Why

Production failures are debugged by grepping stdout JSON logs after the
fact: no aggregation, no deduplication, no release attribution, no alerts,
and django-q2 worker errors are the easiest to lose. The structlog →
stdlib logging bridge already routes every application event through
Python's `logging` module, which is exactly what Sentry-protocol error
tracking SDKs hook into — so error tracking can be added with one
dependency, one settings component, and zero application-code changes.

## What Changes

- **Sentry-protocol error tracking for the backend**, via the official
  `sentry-sdk` Python package (Django integration). Vendor-neutral by
  construction: the SDK ships to whatever DSN it is given — sentry.io or
  Better Stack (which ingests the Sentry SDK protocol natively) — so the
  vendor choice is an ops/account decision, not a code decision.
- **Activation is DSN-gated**: no `SENTRY_DSN` → SDK stays fully disabled.
  Development and test environments set no DSN and are unaffected; CI
  needs no credentials.
- **Release and environment tagging** from values the build already
  produces: `release = GIT_HASH`, `environment = ENVIRONMENT`
  (production/staging/…), giving per-deploy error attribution.
- **Breadcrumbs from existing logs for free**: the default logging
  integration turns existing structlog output (bridged through stdlib
  logging) into the breadcrumb trail of each captured event; `error`+ log
  calls become events. No log-format change — JSON lines on stdout stay
  exactly as they are.
- **Opt-in performance tracing at a controlled sample rate** (default low,
  env-configurable; health checks excluded), covering Django views, DB
  queries, and outgoing httpx calls to hut providers.
- **Privacy-safe defaults**: `send_default_pii=False` (no user IPs or
  emails leave the system unless explicitly changed later).

Non-goals: frontend error tracking / RUM (separate change for the Quasar
app), shipping stdout logs to a vendor (possible later; independent of
this change), uptime/status-page monitoring, changing the API contract
(no `/v1` changes, no API version bump).

## Capabilities

### New Capabilities

- `error-tracking`: backend error tracking lifecycle — activation gating,
  release/environment attribution, log-to-breadcrumb bridging, event
  capture semantics, performance-tracing opt-in with sampling, and PII
  defaults.

### Modified Capabilities

(none — no existing spec's requirements change; logging output format and
all API contracts are untouched.)

## Impact

- **Dependencies**: add `sentry-sdk>=2.72,<3` to `pyproject.toml`
  (runtime dependency; `uv.lock` updated).
- **Settings**: new `server/settings/components/sentry.py`, included first
  in `server/settings/__init__.py` (before `logging.py`, so the logging
  hook is installed before logging is configured).
- **django-q2**: `Q_CLUSTER["error_reporter"]` enables an in-repo Sentry
  reporter (`server/core/q2_sentry.py`, registered via the
  `djangoq.errorreporters` entry point) — q2 swallows task exceptions
  otherwise, so the SDK never sees them.
- **Configuration**: new environment variables `SENTRY_DSN` (activation),
  `SENTRY_TRACES_SAMPLE_RATE` (optional, default low), read via
  python-decouple like all other config. Staging/production get the DSN
  via Infisical; nothing in `.env.test`.
- **Runtime**: works under both gunicorn WSGI and the ASGI/uvicorn worker
  mode (`ASGI_ENABLED=1`); django-q2 cluster processes report through the
  same SDK.
- **No changes** to: API endpoints/responses, database schema, logging
  format, admin, or frontend.
