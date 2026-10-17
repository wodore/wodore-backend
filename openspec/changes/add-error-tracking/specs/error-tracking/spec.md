## ADDED Requirements

### Requirement: Error tracking activation is DSN-gated
The system SHALL initialize the error-tracking SDK only when a non-empty
`SENTRY_DSN` is configured; without it, the SDK SHALL NOT be initialized
and no telemetry SHALL leave the process. Test and development
environments SHALL remain unaffected because they set no DSN.

#### Scenario: No DSN configured

- **WHEN** the settings load without `SENTRY_DSN` (development, test, CI)
- **THEN** the SDK is not initialized and application behavior is identical to pre-change behavior

#### Scenario: DSN configured

- **WHEN** `SENTRY_DSN` is set to a valid Sentry-protocol DSN (sentry.io or a compatible receiver such as Better Stack)
- **THEN** the SDK initializes once at settings load and routes error events to that DSN

### Requirement: Release and environment attribution
Every captured event SHALL carry `release` set to the build's `GIT_HASH`
and `environment` set to the deployment's `ENVIRONMENT`, identically in
staging and production (one release scheme across environments), and
SHALL additionally carry the package semver as an `app_version` tag for
human-readable filtering. No new build steps SHALL be required.

#### Scenario: Error attributed to a deploy

- **WHEN** an error is captured on staging or production
- **THEN** the event is tagged with the exact commit hash built into the running image and the environment name (e.g. `staging`, `production`)

#### Scenario: Cross-environment correlation

- **WHEN** the same commit is deployed to both staging and production and errors occur in both
- **THEN** the events share the same `release` value (differing only in `environment`) and both carry the same `app_version` tag

### Requirement: Existing logs become breadcrumbs without format change
The logging integration SHALL record existing stdlib-bridged structlog
events (level INFO and above) as breadcrumbs on captured events, and
SHALL report log records at level ERROR or above as error events. The
console log output format (JSON lines in production, colored console in
development) SHALL remain unchanged.

#### Scenario: Structlog breadcrumbs attach to an error

- **WHEN** application code logs INFO-level structlog events and then an exception propagates
- **THEN** the captured event includes those prior log entries as breadcrumbs

#### Scenario: Structlog error becomes an event

- **WHEN** application code logs at `error` level or higher through structlog
- **THEN** an error event is captured (no exception required), while stdout output stays byte-compatible JSON lines

### Requirement: Unhandled errors are captured in all server runtimes
Unhandled exceptions SHALL be captured in gunicorn WSGI workers, ASGI/uvicorn workers (`ASGI_ENABLED=1`), and django-q2 cluster processes, in each case with the same release/environment tagging.

#### Scenario: Exception in an HTTP request

- **WHEN** a view raises an unhandled exception
- **THEN** an error event with stack trace and request context is captured, regardless of WSGI or ASGI runtime

#### Scenario: Exception in a background task

- **WHEN** a django-q2 task raises an unhandled exception
- **THEN** the failure is visible as a captured error event attributable to the qcluster process

### Requirement: Performance tracing is opt-in with bounded sampling
Performance tracing SHALL be governed by `SENTRY_TRACES_SAMPLE_RATE`
(default 0.05; `0` disables tracing entirely, leaving errors-only mode).
Health-check requests SHALL NOT generate trace transactions. Requests to
hot geo/tile endpoints SHALL respect the same uniform sample rate — no
per-endpoint special-casing exists in the initial version.

#### Scenario: Tracing disabled

- **WHEN** `SENTRY_TRACES_SAMPLE_RATE=0` and `SENTRY_DSN` is set
- **THEN** error events are captured but no trace transactions are created

#### Scenario: Health checks never traced

- **WHEN** tracing is enabled and a `/health/` request is served
- **THEN** no transaction is created for it

#### Scenario: Sampled request produces a trace

- **WHEN** tracing is enabled at the default rate and sampled requests are served
- **THEN** transactions include spans for the Django view, database queries, and outgoing httpx calls to hut providers

### Requirement: No personally identifiable information is sent
The SDK SHALL be configured with `send_default_pii=False` so user
identities, IP addresses, cookies, and request bodies are not attached to
events.

#### Scenario: Error during an authenticated request

- **WHEN** an error is captured for a request made by an authenticated admin or API user
- **THEN** the event contains no user identifier, IP address, or session data

### Requirement: Rollback by configuration only
Disabling error tracking SHALL require only removing (or emptying)
`SENTRY_DSN` and redeploying — no code change, schema change, or data
migration. Switching between Sentry-protocol-compatible vendors SHALL
require only changing the DSN.

#### Scenario: Disable in production

- **WHEN** `SENTRY_DSN` is removed from the environment and the service redeploys
- **THEN** no telemetry is sent and all other behavior is unchanged
