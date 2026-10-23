## ADDED Requirements

### Requirement: Shared throttle counter backend
Throttling state SHALL live in the dedicated `throttling` cache alias, backed
by a cache shared across all workers (DatabaseCache in production), so limits
are enforced process-wide.

#### Scenario: Production uses a shared backend

- **WHEN** the production settings assemble `CACHES`
- **THEN** the `throttling` alias resolves to a shared cache backend and dmr's unsafe-backend guard passes without warning

#### Scenario: Dev and tests stay local

- **WHEN** DJANGO_ENV is development or test
- **THEN** the `throttling` alias resolves to LocMemCache with dmr's unsafe-cache check explicitly satisfied

### Requirement: Proxy-aware client identity
Throttle keys SHALL be derived from the client IP resolved as the first
`X-Forwarded-For` entry when present, falling back to `REMOTE_ADDR` — the
same convention as the visits visitor hash — not from `REMOTE_ADDR` alone.

#### Scenario: Request behind the reverse proxy

- **WHEN** a request arrives with `X-Forwarded-For: 203.0.113.7, 10.0.0.1`
- **THEN** throttle counters are keyed on `203.0.113.7`

#### Scenario: Direct request without the header

- **WHEN** a request arrives with no `X-Forwarded-For` header
- **THEN** throttle counters are keyed on `REMOTE_ADDR`

### Requirement: Availability endpoints are rate-limited per client
The three availability endpoints (`get_hut_availability_geojson`,
`get_hut_availability_current`, `get_hut_availability_trend`) SHALL apply a
per-client-IP burst limit (default 120/min) and a per-client-IP daily volume
limit (default 2000/day); both limits SHALL be configurable via environment
without code changes.

#### Scenario: Burst limit trips

- **WHEN** one client exceeds the burst limit within a minute
- **THEN** the endpoint answers 429 with a `Retry-After` header

#### Scenario: Daily volume limit trips

- **WHEN** one client stays under the burst limit but exceeds the daily volume limit
- **THEN** the endpoint answers 429 with a `Retry-After` header reflecting the day-window reset

#### Scenario: Normal frontend session is unaffected

- **WHEN** a client performs a typical map + hut-detail session (geojson plus a handful of current/trend calls)
- **THEN** no response is throttled

### Requirement: Throttled responses follow the standard error contract
Throttle rejections SHALL answer 429 in the Wodore error body shape
(`{"code", "detail"}`) with the machine-readable code `throttled` and
rate-limit response headers supplied by dmr.

#### Scenario: Error body shape

- **WHEN** any throttled endpoint rejects a request
- **THEN** the response body is JSON with `code` `"throttled"` and a human-readable `detail`, and carries `Retry-After` plus `X-RateLimit-*` headers

### Requirement: Feedback throttling uses the shared backend and client key
The feedback POST endpoint SHALL keep its 5/min limit but key counters on the
proxy-aware client identity in the shared throttle backend.

#### Scenario: Feedback limit is per client

- **WHEN** five feedback submissions arrive from one client within a minute
- **THEN** the sixth submission from that client answers 429 with `Retry-After`

### Requirement: Non-throttled surfaces stay exempt
Endpoints not listed as throttled (health, version, sitemap/SEO, OpenAPI,
all other read endpoints) SHALL answer without throttle counters or
rate-limit headers.

#### Scenario: Health endpoint unthrottled

- **WHEN** the health endpoint is hit repeatedly beyond any limit
- **THEN** responses are never 429 due to throttling
