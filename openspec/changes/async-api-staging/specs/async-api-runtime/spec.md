# Spec Delta: async-api-runtime

## ADDED Requirements

### Requirement: ASGI serving with sync-first endpoints
The API SHALL be served over ASGI (uvicorn worker via gunicorn, `server.asgi`, switchable via `ASGI_ENABLED`). Endpoint handlers SHALL stay synchronous by default (Django auto-adapts sync views into bridged threads); explicit sync-core wrappers (one `sync_to_async` bridge per request) SHALL be used only where dmr auth hooks or explicit control require async. Endpoints with genuinely independent external I/O MAY be native async (template: the og static map, #259); blanket native conversion is rejected (PoC: native burst8 13.0s vs sync-core 9.2–9.9s).

#### Scenario: Sync view served under ASGI
- **WHEN** a client requests any `/v1/` endpoint under ASGI
- **THEN** the sync handler runs in a bridged thread and returns the same response body, headers (including `Api-Version` and ETag semantics), and status code as under WSGI

#### Scenario: Handler cores stay sync-callable
- **WHEN** a management command or unit test invokes a controller handler directly
- **THEN** it executes without any async context or bridge

### Requirement: No blocking calls on the event loop
Application code executing on the event loop SHALL NOT perform blocking operations. All ORM access, network calls (including OIDC token introspection), and filesystem operations SHALL run inside `sync_to_async` bridges or async clients. CI SHALL enforce ruff `ASYNC` lint rules on all async functions.

#### Scenario: Lint blocks a blocking call in async code
- **WHEN** a pull request adds a blocking sleep or synchronous HTTP call directly inside an async function
- **THEN** CI fails with a ruff `ASYNC` rule violation

#### Scenario: Token introspection never runs on the loop
- **WHEN** the legacy Zitadel introspection validator validates a bearer token on an async endpoint
- **THEN** the network call executes inside a bridge or async HTTP client, never directly on the event loop

### Requirement: Event-loop lag watchdog
The application SHALL run a heartbeat task during the ASGI lifespan that measures event-loop lag and emits a warning-level log event when lag exceeds 250ms.

#### Scenario: Slow blocking segment detected
- **WHEN** event-loop lag exceeds 250ms
- **THEN** a structured warning event with the measured lag is logged

### Requirement: Database connection pooling for async mode
When ASGI mode is enabled (`POSTGRES_POOL=1`), the database configuration SHALL use the psycopg3 connection pool (env-gated, shipped in #259) with `CONN_MAX_AGE` set to 0. The pool SHALL configure a checkout (`getconn`) timeout of ~2 seconds and a per-worker `max_size` cap such that workers × max_size stays within the pod's DB connection budget (guidance: 3 × 4–5).

#### Scenario: Pool replaces persistent connections
- **WHEN** the app runs in ASGI mode and serves concurrent requests
- **THEN** database connections are checked out from the psycopg pool and no per-request persistent connections are kept via `CONN_MAX_AGE`

#### Scenario: Pool exhaustion fails fast instead of wedging
- **WHEN** concurrent demand exceeds the pool budget under a burst
- **THEN** checkouts fail within the short timeout (fast 5xx) instead of queuing 30s, and the process recovers without a restart (PoC counter-example: 40× burst wedged until restart with the default timeout)

#### Scenario: Pool tuned via environment
- **WHEN** the operator sets the pool environment variables
- **THEN** the psycopg pool picks up size and timeout without code changes

### Requirement: Async-capable custom middleware
The custom middlewares (`EnvironmentHeadersMiddleware`, `LoggingContextVarsMiddleware`, `ApiVersionMiddleware`) SHALL be async-capable so that no per-request thread adaptation is inserted for them on the ASGI stack. Request-context (contextvar) propagation SHALL survive the async/thread bridge without duplication or loss.

#### Scenario: API version middleware works without adaptation
- **WHEN** a request with a pinned `Api-Version` header traverses the middleware chain to an async controller
- **THEN** the response downgrade transform is applied identically to WSGI behavior and the middleware runs natively async (no "adapted for middleware" debug log for custom middlewares)

#### Scenario: Request log context continuity
- **WHEN** a request flows through `LoggingContextVarsMiddleware` into an async controller's bridged core
- **THEN** all log events for that request carry the same request identifier

### Requirement: Unchanged API contract under ASGI
Switching the runtime to ASGI SHALL NOT change any observable API behavior: OpenAPI schema, status codes, error contract, ETag/304 behavior, `Api-Version` downgrade transforms, and cache-control headers remain identical to the WSGI deployment.

#### Scenario: Contract tests pass on both runtimes
- **WHEN** the full contract test suite and schemathesis runs execute against the ASGI application
- **THEN** all assertions that passed against the WSGI application pass unchanged

### Requirement: App-level request timeout under ASGI
Because uvicorn workers heartbeat continuously (gunicorn `--timeout` is inert under ASGI), the application SHALL enforce its own request-level timeout with the standard error contract, so runaway handlers cannot hold connections indefinitely (PoC: 2.85 MB list request ran 52s with no kill).

#### Scenario: Runaway request is cut off
- **WHEN** a request exceeds the configured app-level timeout under ASGI
- **THEN** it is cancelled and answered with the standard error contract response instead of running unbounded
