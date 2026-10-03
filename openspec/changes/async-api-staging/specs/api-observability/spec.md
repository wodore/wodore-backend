# Spec Delta: api-observability

## ADDED Requirements

### Requirement: Structured request-duration access logging
Every completed API response SHALL emit exactly one structured log event containing method, path, status code, and request duration in milliseconds. The event SHALL be emitted for all status codes including 2xx/3xx (which today are invisible in production logs) and SHALL be cheap enough to leave enabled in production.

#### Scenario: Successful request is logged
- **WHEN** a client request completes with a 200 response
- **THEN** one structured event with method, path, status 200, and duration ≥ 0 is logged

#### Scenario: Not-modified response is logged
- **WHEN** a hut detail request with a matching ETag completes as 304
- **THEN** one structured event with status 304 and its duration is logged, enabling cache-effectiveness measurement

#### Scenario: Rejected request is logged
- **WHEN** a request fails validation or auth and returns a 4xx error contract response
- **THEN** one structured event with the status code and duration is logged

### Requirement: Log volume stays proportional to traffic
The access logging SHALL NOT emit more than one event per request and SHALL NOT log response bodies, query strings containing tokens, or Authorization headers, keeping production log volume proportional to request count.

#### Scenario: No sensitive data in access events
- **WHEN** an authenticated request with a bearer token is logged
- **THEN** the access event contains no token material or authorization header content

### Requirement: Baseline metrics before runtime change
The request-duration logging SHALL be deployed to production while the stack is still WSGI, establishing a latency baseline for at least one week of real traffic before the ASGI rollout, so before/after comparison is possible.

#### Scenario: Baseline exists before ASGI rollout
- **WHEN** stage 2 (ASGI) deploys to production
- **THEN** stage 1 duration logs from the WSGI period are available for comparison
