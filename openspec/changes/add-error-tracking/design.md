## Context

The backend logs through **structlog bridged into stdlib logging**
(`server/settings/components/logging.py`): structlog is configured with
`structlog.stdlib.LoggerFactory()` and its final processor is
`ProcessorFormatter.wrap_for_formatter`, so every structlog event — app
code, Django, third-party — passes through Python's `logging` module and
one console `StreamHandler` (colored console in dev, JSON lines on stdout
in production). Settings are composed with django-split-settings
(`server/settings/__init__.py`, ordered include list; environment files
re-import base tuples; `components/registry.py` must stay last). The
docker build already injects `GIT_HASH` (full commit SHA), and settings
expose `ENVIRONMENT` (production/staging/development/test) plus
`GIT_HASH`. Runtime is gunicorn with a WSGI/ASGI switch
(`ASGI_ENABLED=1` → uvicorn workers on `server.asgi`), and long-running
jobs run in django-q2 clusters. External config arrives via python-
decouple (`config(...)`) with Infisical as the secret store
(`get_env.sh` exports per-environment at deploy time; k8s inherits).

No error tracking exists today. The chosen client is the official
`sentry-sdk` Python package (Django integration): its default
`LoggingIntegration` hooks `logging.Handler.handle`, which — given the
stdlib bridge above — means existing structlog events become breadcrumbs
and `error`+ records become events without touching any application code
or the log format.

## Goals / Non-Goals

**Goals:**

- Aggregated, deduplicated backend error events with stack traces,
  release (`GIT_HASH`) and environment attribution, and alerting.
- Breadcrumbs from existing logs with zero log-format change.
- Vendor-neutral client wiring: `sentry-sdk` speaking the Sentry protocol
  to whatever DSN it is given (sentry.io **or** Better Stack, which
  ingests the same protocol natively).
- Graceful no-op: absent `SENTRY_DSN`, the SDK is not initialized;
  dev/test/CI behave exactly as today.
- Opt-in performance tracing (Django views, DB queries, outgoing httpx)
  at a low, env-controlled sample rate, excluded from health checks.
- Privacy-safe defaults (`send_default_pii=False`).

**Non-Goals:**

- Frontend error tracking / RUM for the Quasar app (separate change).
- Shipping stdout logs to the vendor (later, independent: Vector/agent).
- Uptime/status-page monitoring, on-call tooling.
- Any API contract, schema, or log-format change.
- Choosing the vendor in code — DSN value only; sentry.io vs Better Stack
  is an ops/account decision (both can even be evaluated against the same
  build by swapping the DSN).

## Decisions

### D1. Client: official `sentry-sdk`, not an OpenTelemetry-first stack

`sentry-sdk>=2.72,<3` with default auto-integrations
(`DjangoIntegration`, `HttpxIntegration` — both auto-enabled) plus
`AsyncioIntegration` added explicitly (not auto-enabled; needed for the
ASGI/uvicorn runtime). Alternatives considered: OTel SDK with an OTLP
collector (more moving parts; Better Stack's tracing path, but overkill
for errors-first and no benefit on sentry.io); community
`structlog-sentry` processor (redundant — the stdlib bridge already
feeds the default logging integration).

### D2. Vendor neutrality via DSN-only coupling

Activation and destination are both the `SENTRY_DSN` env var. Better
Stack documents Sentry-SDK compatibility (its error tracking ingests the
Sentry protocol; Python included), so the identical code serves either
vendor. Consequence: protocol features that a compatible vendor does not
implement (if any) degrade there gracefully — the SDK's transport just
sends envelopes. Known nuance: with Better Stack, backend *performance
tracing* may be limited compared to sentry.io (their tracing product is
OTel-based); if that matters at evaluation time, it is a vendor decision,
not a code change.

### D3. Placement: new `components/sentry.py`, included FIRST

`sentry_sdk.init()` runs at import of a new settings component placed
before `components/logging.py` in the include list: initialization
installs the logging hook before `logging.config.dictConfig` builds
handlers, and errors raised during settings import itself are still
captured. It must not go in `components/registry.py` (stays last) or the
environment files (they run after logging too). The component reads only
env vars — it has no ordering dependency on other components' names.

### D4. Activation gating: `SENTRY_DSN` presence, nothing else

`config("SENTRY_DSN", default=None)`; falsy → `sentry_sdk.init` is not
called at all (not "initialized with empty DSN"). Test env sets no DSN,
so pytest/CI never ship data. Optional secondary knobs, all with
defaults so the only *required* deployment change is the DSN:
`SENTRY_TRACES_SAMPLE_RATE` (float, default `0.05`; `0` disables tracing
entirely → errors-only mode), `SENTRY_ENVIRONMENT` (default: the
settings `ENVIRONMENT`).

### D5. Release = commit hash everywhere; semver as an event tag

Docker builds run per push to `main` (`docker.yml`), so deploys are
per-commit while the bumpversion semver only moves at release-cadence:
`release=GIT_HASH` (injected into every image, all build triggers) keeps
deploy-exact granularity and stays **uniform across staging and
production** (same code → same release id → cross-env correlation).
The semver is *also* available at runtime via package metadata
(`importlib.metadata.version("wodore-backend")`) and is attached as an
`app_version` event tag (e.g. `sentry_sdk.set_tag` after init) for
human-readable filtering. No new build steps; this yields "errors
introduced by deploy X" grouping and vendor-side release tracking for
free.

### D6. Tracing: low uniform sample rate + health-check exclusion via traces_sampler

`traces_sample_rate` from D4 (0.05 default — the geo/tile API is too hot
for 1.0; one Django request easily fans out into many spans), health
checks excluded by a minimal `traces_sampler` callback that returns 0
for `/health/` transactions and the configured rate for everything else.
Note: sentry-sdk 2.72 has **no** `ignore_transactions` init option — the
sampler is the supported mechanism (verified against the installed
SDK); `rate == 0` therefore also means "no transactions at all"
(errors-only mode), keeping a single knob. `send_default_pii=False`
stays the fixed default (GDPR); no user/IP data attached.

### D7. Logging: keep format, accept breadcrumb cosmetics

JSON-lines stdout is unchanged (Sentry reads nothing from stdout — it
hooks in-process). Because structlog hands the event *dict* to stdlib
(`wrap_for_formatter`), breadcrumbs may render as a dict-repr rather
than the clean event string. Accepted as cosmetic-only for now; a tiny
processor to shape breadcrumb text can be added later if it annoys.
Explicitly configuring `LoggingIntegration(level=INFO,
event_level=ERROR)` — same as the defaults — keeps intent visible in
code.

### D8. Deployment/rollback is a single env var

Adding `SENTRY_DSN` to Infisical staging → prod (no k8s manifest change:
`get_env.sh` exports it automatically). Rollback = remove/empty the DSN
and redeploy; the code path is inert without it. Roll-forward between
vendors = swap DSN.

## Risks / Trade-offs

- [New runtime dependency in every process incl. qcluster workers] →
  pinned major (`>=2.72,<3`), SDK is inert without DSN; no DB/migration
  impact.
- [Vendor protocol gaps on Sentry-compatible receivers (e.g. tracing on
  Better Stack)] → errors are the primary payload and documented
  compatible; tracing rate is env-tunable to `0`; vendor swap is DSN-only
  (D2/D8).
- [Breadcrumb readability via ProcessorFormatter dict-reprs] → accepted
  cosmetic trade-off (D7); fixable later with a small processor.
- [Quota/cost or noisy alerts (bot scans, 4xx floods)] → low trace
  sampling; inbound filters/ownership configured at the vendor (ops
  task, not code); errors-only mode remains available (`rate=0`).
- [PII leakage if defaults are changed carelessly later] → `send_default_pii`
  hard-defaulted off in the component; documented in AGENTS.md.
- [SDK init ordering regressions if settings include order changes] →
  placement documented here and in tasks; a settings-import test pins
  "no DSN → no init".

## Migration Plan

1. Merge code (inert everywhere; no DSN anywhere yet).
2. Add `SENTRY_DSN` (staging) to Infisical; deploy staging; verify: test
   exception surfaces with correct release/environment, breadcrumbs
  present, qcluster failure captured, `/health/` produces no
   transactions.
3. Vendor evaluation window (optional A/B: sentry.io vs Better Stack by
   swapping DSN on staging).
4. Add `SENTRY_DSN` (production); optionally raise/lower
   `SENTRY_TRACES_SAMPLE_RATE` based on observed volume.
5. Rollback at any step: empty the DSN and redeploy (or set
   `SENTRY_TRACES_SAMPLE_RATE=0` for tracing-only rollback).

## Open Questions

- Vendor/account: Better Stack (100k exceptions/mo free, unlimited
  members, unified with logs later) vs sentry.io (mature, tracing via
  same SDK) — ops decision; code is identical (D2). Leaning Better
  Stack first per evaluation, revisit after the staging trial.
- Does Better Stack ingest `sentry-sdk` *spans* (not just errors)? To
  verify during the staging trial; only affects the tracing goal, not
  the error-tracking core.
- Alert routing destination (Slack? email?) — vendor-side configuration,
  decided during staging setup.
