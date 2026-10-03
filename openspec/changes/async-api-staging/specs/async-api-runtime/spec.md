# Spec Delta: async-api-runtime

## ADDED Requirements

### Requirement: ASGI serving with sync-core controllers
The API SHALL be served over ASGI (uvicorn worker via gunicorn, `server.asgi`), with every dmr controller endpoint implemented as a thin async wrapper whose handler logic executes inside a single `sync_to_async` bridged sync core. Handler cores SHALL remain callable from synchronous contexts (tests, management commands) unchanged.

#### Scenario: Request served through async wrapper
- **WHEN** a client requests any `/v1/` endpoint under ASGI
- **THEN** the endpoint's async wrapper delegates to its sync core via one `sync_to_async` bridge and returns the same response body, headers (including `Api-Version` and ETag semantics), and status code as the previous WSGI deployment

#### Scenario: Sync core reused outside the request path
- **WHEN** a management command or unit test invokes a controller's sync core directly
- **THEN** the core executes without any async context or bridge

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
The database configuration SHALL use the psycopg3 connection pool (`"pool": True` in `OPTIONS`) with `CONN_MAX_AGE` set to 0 and connection health checks enabled. The pool size SHALL be configurable via environment and default to 10 per pod.

#### Scenario: Pool replaces persistent connections
- **WHEN** the app runs in ASGI mode and serves concurrent requests
- **THEN** database connections are checked out from the psycopg pool and no per-request persistent connections are kept via `CONN_MAX_AGE`

#### Scenario: Pool size tuned via environment
- **WHEN** the operator sets the pool-size environment variable
- **THEN** the psycopg pool is created with that size without code changes

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

### Requirement: Django 6.1 baseline for async features
The application SHALL run on Django 6.1.x before ASGI rollout, making the async cache framework, async sessions, and dual-mode bundled middleware available.

#### Scenario: Bundled middleware runs dual-mode
- **WHEN** the ASGI stack processes a request through Django's bundled middleware (e.g. sessions, common)
- **THEN** the middleware executes natively without thread adaptation
